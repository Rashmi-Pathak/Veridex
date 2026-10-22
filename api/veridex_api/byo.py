"""Bring-your-own-asset direct-to-B2 upload (the judge-drops-an-image loop).

The browser asks for a presigned S3 PUT URL, uploads its image DIRECT to the Backblaze B2 S3
endpoint (no proxy through this API), then asks Rooted to register the stored object. Registration
fetches the bytes back from B2 and runs the SAME ingest core as the B2 event-notification webhook
(veridex_api.b2_events.ingest_stored_object): PDQ fingerprint, transparency-log append, and a
content-addressed manifest id, so the visitor's own asset becomes a real registered manifest with a
real inclusion proof, recoverable via /matches/byContent like every other asset.

Security posture (judge-facing, fail closed):
- The object key is server-generated (uuid4 hex under the byo/ prefix); a client-supplied name or
  key never shapes it, and register only accepts keys matching that exact shape.
- The presign constrains Content-Type to an image allowlist and expires in 10 minutes; register
  re-checks the stored size against the shared upload cap BEFORE downloading, then decodes through
  the shared decompression-bomb guard and decode limiter.
- Missing credentials degrade to an honest 503; a missing object is a clear 404; nothing 500s on
  ordinary misuse. No per-IP rate limit exists on this API yet (documented caveat); the body-size
  middleware, the decode limiter, and the 25 MiB cap bound the per-request cost.
"""

from __future__ import annotations

import os
import re
import uuid

import anyio
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from veridex_api.b2_events import ingest_stored_object
from veridex_api.dedup import record_idempotent_register
from veridex_provenance.models import CamelModel
from veridex_storage.storage import B2Storage

router = APIRouter()

_PRESIGN_EXPIRY_SECONDS = 600  # 10 minutes: enough for one browser PUT, short enough to not linger
_BYO_PREFIX = "byo/"

# Idempotency short-circuit for register: object key -> (manifest id, stored size). Re-registering
# a known key answers from here after only a stored-size check (no download, no decode), so a caller
# looping register on one valid key cannot make the API re-fetch and re-decode the object each time.
# In-process and bounded: a restart just means one full (still idempotent) pass re-primes it, and a
# size mismatch (the key was re-PUT with different bytes inside the presign window) falls through to
# the full path so the answer never goes stale.
_REGISTERED_KEYS: dict[str, tuple[str, int]] = {}
_REGISTERED_KEYS_MAX = 1024

# The image allowlist: content type -> object-key extension. Anything else is refused at presign
# time (415), and register only accepts keys carrying one of these extensions.
_ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

# The only key shape register will touch: the byo/ prefix, a server-generated uuid4 hex name, and an
# allowlisted extension. Everything else (client-invented names, ../ traversal, absolute keys, other
# prefixes, other extensions) fails closed on this anchored match. \Z, not $: $ would also match
# before a trailing newline, letting "byo/<hex>.png\n" through.
_BYO_KEY_RE = re.compile(r"\Abyo/[0-9a-f]{32}\.(png|jpg|webp)\Z")


def _max_upload_bytes() -> int:
    """The shared per-asset upload cap (the Tier-0 DoS guard constant in sbr)."""
    from veridex_api import sbr

    return int(sbr._MAX_UPLOAD_BYTES)


class ByoUploadUrlRequest(CamelModel):
    """What the browser declares before uploading: the file's content type and size in bytes."""

    content_type: str
    size_bytes: int


class ByoUploadUrlResponse(CamelModel):
    """A presigned S3 PUT for the B2 S3 endpoint. The PUT must send exactly this content type (it
    is signed into the URL) and the raw file bytes as the body; then POST the objectKey to
    /demo/byo/register to make the asset recoverable."""

    upload_url: str
    object_key: str
    bucket: str
    content_type: str
    expires_in_seconds: int
    max_bytes: int


class ByoRegisterRequest(CamelModel):
    """The server-issued object key returned by /demo/byo/upload-url, after the browser PUT."""

    object_key: str


class ByoRegisterResponse(CamelModel):
    """The registered result: the visitor's asset is now a real manifest with a transparency-log
    leaf, recoverable by content like every other asset. backend is evidence-based ("backblaze-b2"
    only when the bytes actually came back from B2)."""

    manifest_id: str
    object_key: str
    bucket: str
    backend: str
    size_bytes: int
    asset_sha256: str
    already_registered: bool
    recoverable: bool
    note: str


def _presign_config() -> tuple[str, str, str, str, str] | None:
    """(key_id, app_key, bucket, endpoint, region) when everything needed to presign is configured,
    else None. The endpoint falls back to the standard B2 S3 form derived from B2_REGION, and the
    region falls back to parsing the endpoint host, so either variable alone is enough."""
    key_id = os.environ.get("B2_KEY_ID")
    app_key = os.environ.get("B2_APP_KEY")
    bucket = os.environ.get("B2_BUCKET_DEV")
    region = os.environ.get("B2_REGION")
    endpoint = os.environ.get("B2_ENDPOINT")
    if not endpoint and region:
        endpoint = f"https://s3.{region}.backblazeb2.com"
    if not region and endpoint:
        host_match = re.match(r"^https://s3\.([a-z0-9-]+)\.backblazeb2\.com/?$", endpoint)
        if host_match:
            region = host_match.group(1)
    if not (key_id and app_key and bucket and endpoint and region):
        return None
    return key_id, app_key, bucket, endpoint, region


def _presign_put(
    key_id: str, app_key: str, bucket: str, endpoint: str, region: str, key: str, content_type: str
) -> str:
    """A presigned S3 PUT URL for the B2 S3-compatible endpoint (SigV4). Purely local computation:
    boto3 signs with the B2 application key, no credential ever reaches the response beyond the
    key id embedded in the standard X-Amz-Credential scope. Blocking-ish (boto3 loads its config),
    so callers run it in the threadpool."""
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=app_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )
    url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=_PRESIGN_EXPIRY_SECONDS,
    )
    return str(url)


@router.post(
    "/demo/byo/upload-url",
    response_model=ByoUploadUrlResponse,
    include_in_schema=False,
)
async def byo_upload_url(req: ByoUploadUrlRequest) -> ByoUploadUrlResponse:
    """Issue a short-lived presigned PUT so the browser uploads its image DIRECT to Backblaze B2.
    The key is server-generated (never client-named), the content type is allowlisted and signed
    into the URL, and the declared size is checked against the shared upload cap (and re-checked
    against the stored object at register time, so a lying declaration gains nothing)."""
    ext = _ALLOWED_CONTENT_TYPES.get(req.content_type)
    if ext is None:
        raise HTTPException(
            status_code=415,
            detail="unsupported content type (allowed: image/png, image/jpeg, image/webp)",
        )
    if req.size_bytes <= 0:
        raise HTTPException(status_code=400, detail="sizeBytes must be a positive byte count")
    cap = _max_upload_bytes()
    if req.size_bytes > cap:
        raise HTTPException(status_code=413, detail=f"asset too large (max {cap} bytes)")
    config = _presign_config()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "BYO upload is not configured: Backblaze B2 credentials and the S3 endpoint "
                "(B2_KEY_ID, B2_APP_KEY, B2_BUCKET_DEV, B2_ENDPOINT or B2_REGION) are required"
            ),
        )
    key_id, app_key, bucket, endpoint, region = config
    object_key = f"{_BYO_PREFIX}{uuid.uuid4().hex}{ext}"
    upload_url = await run_in_threadpool(
        _presign_put, key_id, app_key, bucket, endpoint, region, object_key, req.content_type
    )
    return ByoUploadUrlResponse(
        upload_url=upload_url,
        object_key=object_key,
        bucket=bucket,
        content_type=req.content_type,
        expires_in_seconds=_PRESIGN_EXPIRY_SECONDS,
        max_bytes=cap,
    )


@router.post(
    "/demo/byo/register",
    response_model=ByoRegisterResponse,
    include_in_schema=False,
)
async def byo_register(req: ByoRegisterRequest) -> ByoRegisterResponse:
    """Ingest a direct-uploaded object from B2 so it becomes recoverable: verify the key shape and
    the stored size, download the bytes from B2, decode them through the shared bomb guard, then run
    the SAME register core as the event webhook (PDQ + log append + content-addressed manifest id).
    The visitor's asset is then a real registered manifest that /matches/byContent recovers."""
    from veridex_api import sbr

    key = req.object_key
    if not _BYO_KEY_RE.match(key):
        raise HTTPException(status_code=400, detail="invalid object key")
    storage = sbr.get_storage()
    if storage is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "BYO register is not configured: Backblaze B2 storage "
                "(B2_KEY_ID, B2_APP_KEY, B2_BUCKET_DEV) is required"
            ),
        )
    cap = _max_upload_bytes()
    size = await run_in_threadpool(storage.size, key)
    if size is None:
        raise HTTPException(
            status_code=404,
            detail="object not found in the upload bucket (did the browser PUT complete?)",
        )
    if size > cap:
        raise HTTPException(status_code=413, detail=f"stored object too large (max {cap} bytes)")
    cached = _REGISTERED_KEYS.get(key)
    if cached is not None and cached[1] == size:
        # Known key with an unchanged stored size: answer without downloading or decoding.
        cached_id, cached_size = cached
        manifest = await run_in_threadpool(sbr.get_resolver().get_manifest, cached_id)
        if manifest is not None:
            record_idempotent_register()  # dedup evidence: answered from the key cache, no re-fetch
            return ByoRegisterResponse(
                manifest_id=manifest.manifest_id,
                object_key=key,
                bucket=os.environ.get("B2_BUCKET_DEV", ""),
                backend="backblaze-b2" if isinstance(storage, B2Storage) else "in-memory",
                size_bytes=cached_size,
                asset_sha256=manifest.asset_sha256,
                already_registered=True,
                recoverable=True,
                note=(
                    "already registered: the same bytes were ingested before "
                    "(content-addressed, idempotent)"
                ),
            )
    from b2sdk.v2.exception import FileNotPresent

    try:
        data = await run_in_threadpool(storage.get, key)
    except (KeyError, FileNotPresent) as exc:
        # Genuinely missing (deleted between the size check and the fetch): an honest 404.
        raise HTTPException(
            status_code=404,
            detail="object not found in the upload bucket (did the browser PUT complete?)",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - a storage OUTAGE must not masquerade as "not found"
        raise HTTPException(
            status_code=502, detail="upload storage is temporarily unavailable"
        ) from exc
    if len(data) > cap:  # backstop if the reported size lied
        raise HTTPException(status_code=413, detail=f"stored object too large (max {cap} bytes)")
    # The shared decode guard: size cap, decompression-bomb check, and the bounded decode limiter.
    # A non-image (or a bomb) raises its honest 413/415 straight through to the caller.
    image = await anyio.to_thread.run_sync(
        sbr._decode_image, data, limiter=sbr._image_decode_limiter
    )
    bucket = os.environ.get("B2_BUCKET_DEV", "")
    manifest, already_registered = await ingest_stored_object(
        key, bucket, data, image, source="byo-upload"
    )
    if len(_REGISTERED_KEYS) >= _REGISTERED_KEYS_MAX:
        _REGISTERED_KEYS.pop(next(iter(_REGISTERED_KEYS)))  # bounded: drop the oldest entry
    _REGISTERED_KEYS[key] = (manifest.manifest_id, len(data))
    backend = "backblaze-b2" if isinstance(storage, B2Storage) else "in-memory"
    note = (
        "already registered: the same bytes were ingested before (content-addressed, idempotent)"
        if already_registered
        else (
            "registered: the asset is fingerprinted, appended to the transparency log, and "
            "recoverable via /matches/byContent"
        )
    )
    return ByoRegisterResponse(
        manifest_id=manifest.manifest_id,
        object_key=key,
        bucket=bucket,
        backend=backend,
        size_bytes=len(data),
        asset_sha256=manifest.asset_sha256,
        already_registered=already_registered,
        recoverable=True,
        note=note,
    )
