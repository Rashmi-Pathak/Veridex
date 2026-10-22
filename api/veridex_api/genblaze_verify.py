"""Genblaze v0.6.0 byte-level output verification (the check `genblaze verify --fetch` shipped).

genblaze v0.6.0 added `genblaze verify --fetch`: on top of the canonical-hash and declared-sha256
checks, it downloads each output asset and compares its actual bytes to the manifest's committed
sha256, with a size_bytes cross-check. This endpoint runs that same byte-level verification on the
real Genblaze asset Rooted stored to Backblaze B2.

genblaze-core re-verifies the native manifest at request time (its Mode 1 integrity, via the fuller
`verification_report`: the canonical hash holds, every output carries a valid sha256, and the
asset metadata is in spec), then the asset bytes are fetched, hashed, and compared to the committed
sha256 and size. The bytes are fetched from B2 with a short-lived presigned GET when B2 is
configured (the bucket is private, so this exercises the restricted-key path v0.6.0 hardened); it
falls back to the committed copy of the same content-addressed bytes when B2 is not reachable, and
degrades to available=false rather than 500. Then Rooted's layer (Ed25519/COSE signing, the C2PA
claim, recovery, the transparency proof) is what Genblaze does not do (its Mode 2 and Mode 3 are
not shipped).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from veridex_provenance.models import CamelModel

router = APIRouter()
logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent / "assets"
_ASSET = _ASSETS / "genblaze-b2-asset.jpg"
_MANIFEST = _ASSETS / "genblaze-b2-manifest.json"

_MAX_ASSET_BYTES = 50 * 1024 * 1024  # a generous cap on the fetched asset (the fixture is ~0.9 MB)
_FETCH_TIMEOUT = 30.0
_PRESIGN_GET_EXPIRY_SECONDS = 120  # a short-lived read URL, used once server-side


class GenblazeVerifyResponse(CamelModel):
    available: bool
    genblaze_version: str | None
    schema_version: str | None
    run_id: str | None
    # genblaze-core's manifest verification (Mode 1): the fuller v0.6.0-era report.
    hash_ok: bool
    outputs_all_sha256: bool
    metadata_in_spec: bool
    manifest_verified: bool
    # The byte-level check `genblaze verify --fetch` added: bytes hash to the committed sha256.
    byte_source: str  # "b2" | "fixture" | "none"
    byte_verified: bool
    size_verified: bool
    declared_sha256: str | None
    fetched_sha256: str | None
    declared_size_bytes: int | None
    fetched_size_bytes: int | None
    asset_host: str | None
    verified: bool
    note: str


def _unavailable(note: str) -> GenblazeVerifyResponse:
    return GenblazeVerifyResponse(
        available=False,
        genblaze_version=None,
        schema_version=None,
        run_id=None,
        hash_ok=False,
        outputs_all_sha256=False,
        metadata_in_spec=False,
        manifest_verified=False,
        byte_source="none",
        byte_verified=False,
        size_verified=False,
        declared_sha256=None,
        fetched_sha256=None,
        declared_size_bytes=None,
        fetched_size_bytes=None,
        asset_host=None,
        verified=False,
        note=note,
    )


def _presign_get(
    key_id: str, app_key: str, bucket: str, endpoint: str, region: str, key: str
) -> str:
    """A short-lived presigned S3 GET for the B2 S3-compatible endpoint (SigV4). Local computation:
    boto3 signs with the B2 application key; no credential leaves the process. Blocking-ish (boto3
    loads its config), so the caller runs it in the threadpool."""
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
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=_PRESIGN_GET_EXPIRY_SECONDS,
    )
    return str(url)


async def _fetch_from_b2(asset_url: str) -> bytes | None:
    """Fetch the asset from B2 with a presigned GET, or None if B2 is unconfigured/unreachable.

    The object key is taken from the manifest's own asset URL, but only when that URL is under the
    configured B2 endpoint and bucket, so an unexpected URL is never fetched. The bucket is private
    (an unauthenticated GET is 403), which is why the read is presigned; a restricted key or a daily
    cap that makes the fetch fail returns None and the caller falls back to the committed copy."""
    from veridex_api.byo import _presign_config

    config = _presign_config()
    if config is None:
        return None
    key_id, app_key, bucket, endpoint, region = config
    prefix = f"{endpoint.rstrip('/')}/{bucket}/"
    if not asset_url.startswith(prefix):
        logger.info("genblaze asset URL is not under the configured B2 bucket; skipping B2 fetch")
        return None
    key = asset_url[len(prefix) :]
    try:
        import httpx

        signed = await run_in_threadpool(
            _presign_get, key_id, app_key, bucket, endpoint, region, key
        )
        chunks: list[bytes] = []
        total = 0
        async with (
            httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=False) as client,
            client.stream("GET", signed) as resp,
        ):
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_ASSET_BYTES:
                    logger.warning("genblaze asset exceeded the fetch cap; skipping B2 fetch")
                    return None
                chunks.append(chunk)
        return b"".join(chunks)
    except Exception as exc:  # noqa: BLE001 - a failed B2 fetch degrades to the committed copy
        logger.warning("genblaze B2 fetch failed (%s); falling back to the committed copy", exc)
        return None


async def _fetch_asset_bytes(asset_url: str | None) -> tuple[bytes | None, str]:
    """The bytes to verify: the live B2 copy when reachable, else the committed content-addressed
    copy. Both are the same bytes (content-addressed), so the byte comparison is real either way;
    byte_source reports which one was checked so the surface stays honest."""
    if asset_url:
        data = await _fetch_from_b2(asset_url)
        if data is not None:
            return data, "b2"
    try:
        return _ASSET.read_bytes(), "fixture"
    except OSError as exc:
        logger.warning("genblaze committed asset unavailable: %s", exc)
        return None, "none"


@router.get("/demo/genblaze-verify", response_model=GenblazeVerifyResponse, include_in_schema=False)
async def genblaze_verify() -> GenblazeVerifyResponse:
    """Run genblaze v0.6.0's byte-level output verification on the B2-stored Genblaze asset:
    genblaze-core re-verifies the manifest (Mode 1), and the asset bytes are fetched and hashed and
    compared to the manifest's committed sha256 and size. Degrades to available=false, never 500."""
    try:
        manifest_json = _MANIFEST.read_text()
    except OSError as exc:
        logger.warning("genblaze fixture manifest unavailable: %s", exc)
        return _unavailable("the Genblaze manifest fixture is unavailable")

    try:
        import genblaze_core
        from genblaze_core.models.manifest import parse_manifest

        gm = parse_manifest(json.loads(manifest_json))
        report = gm.verification_report()
        asset = gm.run.steps[0].assets[0]
        declared_sha256 = asset.sha256
        declared_size_bytes = asset.size_bytes
        asset_url = asset.url
        genblaze_version = getattr(genblaze_core, "__version__", None)
    except Exception as exc:  # noqa: BLE001 - a demo surface must degrade, never 500
        logger.warning("genblaze manifest parse/verify failed: %s", exc)
        return _unavailable("the Genblaze manifest could not be parsed or verified")

    data, byte_source = await _fetch_asset_bytes(asset_url)
    if data is None:
        fetched_sha256: str | None = None
        fetched_size_bytes: int | None = None
        byte_verified = False
        size_verified = False
    else:
        fetched_sha256 = hashlib.sha256(data).hexdigest()
        fetched_size_bytes = len(data)
        byte_verified = fetched_sha256 == declared_sha256
        size_verified = fetched_size_bytes == declared_size_bytes

    hash_ok = bool(report.hash_ok)
    outputs_all_sha256 = not report.unverified_sha256_ids
    metadata_in_spec = not report.invalid_metadata_ids
    manifest_verified = bool(report.ok)
    verified = manifest_verified and byte_verified and size_verified

    asset_host = urlparse(asset_url).hostname if asset_url else None
    if verified:
        where = "from Backblaze B2" if byte_source == "b2" else "from the committed copy"
        note = (
            f"byte-level verification passed: the asset bytes {where} hash to the committed sha256"
        )
    elif not manifest_verified:
        note = "the Genblaze manifest did not fully verify"
    else:
        note = "the asset bytes did not match the committed sha256"

    return GenblazeVerifyResponse(
        available=True,
        genblaze_version=genblaze_version,
        schema_version=gm.schema_version,
        run_id=gm.run.run_id,
        hash_ok=hash_ok,
        outputs_all_sha256=outputs_all_sha256,
        metadata_in_spec=metadata_in_spec,
        manifest_verified=manifest_verified,
        byte_source=byte_source,
        byte_verified=byte_verified,
        size_verified=size_verified,
        declared_sha256=declared_sha256,
        fetched_sha256=fetched_sha256,
        declared_size_bytes=declared_size_bytes,
        fetched_size_bytes=fetched_size_bytes,
        asset_host=asset_host,
        verified=verified,
        note=note,
    )
