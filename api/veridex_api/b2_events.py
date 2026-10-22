"""Backblaze B2 Event-Notification ingest (the B2 data-orchestration axis).

A Backblaze B2 bucket rule POSTs a signed notification to this webhook when an object is created
under a watched prefix. Rooted verifies the HMAC-SHA256 signature, fetches the new object from B2,
fingerprints it, and registers it for provenance recovery + the transparency log. The result: drop
an asset into B2 and it auto-becomes recoverable. Backblaze B2 is an active part of the pipeline
(event-driven orchestration), not just passive storage.

Activation (one-time): set B2_EVENT_SIGNING_SECRET on the API, then add a B2 Event Notification rule
on the bucket targeting POST <api>/webhooks/b2-event with the same hmacSha256SigningSecret and an
objectNamePrefix (default "ingest/"). Until then the webhook refuses unsigned calls and
/demo/b2-events reports not-configured (honest dual-mode).

Security: the signature is verified (constant-time) BEFORE any work; an unconfigured secret refuses
rather than ingesting unsigned; only ObjectCreated events under the watched prefix are processed;
the fetched object is size-capped and decoded through the shared decompression-bomb guard; ingest is
idempotent (B2 may redeliver) via a content-addressed manifest id.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any

import anyio
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image
from starlette.concurrency import run_in_threadpool

from veridex_api.dedup import record_idempotent_register
from veridex_provenance.models import ALG_TRUSTMARK_P, CamelModel, Manifest, SoftBinding

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_OBJECT_BYTES = 25 * 1024 * 1024  # cap a fetched object; skip anything larger
_MAX_EVENTS_PER_REQUEST = 100  # one signed payload cannot drive unbounded fetches/decodes
_RECENT_MAX = 20
_recent: list[dict[str, Any]] = []
_recent_lock = threading.Lock()


def _watch_prefix() -> str:
    return os.environ.get("B2_EVENT_PREFIX", "ingest/")


def _expected_bucket() -> str | None:
    """The bucket the rule is configured on; events for any other bucket are ignored."""
    return os.environ.get("B2_EVENT_BUCKET") or os.environ.get("B2_BUCKET_DEV") or None


def _signing_secret() -> str | None:
    return os.environ.get("B2_EVENT_SIGNING_SECRET") or None


def _verify_signature(raw: bytes, header: str | None, secret: str) -> bool:
    """Constant-time check of the lowercase hex HMAC-SHA256 of the raw body (B2's scheme). A
    malformed (non-hex) header returns False rather than raising, so a crafted header cannot 500."""
    if not header:
        return False
    try:
        provided = bytes.fromhex(header.strip())
    except ValueError:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return hmac.compare_digest(expected, provided)


def _record(entry: dict[str, Any]) -> None:
    with _recent_lock:
        _recent.insert(0, entry)
        del _recent[_RECENT_MAX:]


class B2IngestRecord(CamelModel):
    object_key: str
    manifest_id: str
    bucket: str
    size_bytes: int
    ingested_at: str


class B2EventStatus(CamelModel):
    configured: bool
    watch_prefix: str
    count: int
    recent: list[B2IngestRecord]


async def ingest_stored_object(
    object_key: str, bucket: str, data: bytes, image: Image.Image, *, source: str
) -> tuple[Manifest, bool]:
    """Register B2-stored bytes for provenance recovery and append them to the transparency log.

    The shared core of the event-webhook ingest, reused by the BYO direct-upload path
    (veridex_api.byo) so both run the SAME path: PDQ fingerprint via resolver.register, the log
    append, and a content-addressed manifest id (the same bytes always map to the same manifest, so
    ingest is idempotent across redeliveries and paths). Returns (manifest, already_registered).
    A log-append failure raises HTTPException(500) so a caller never reports ok for a manifest with
    no inclusion proof; a later redelivery heals it via the registered-but-unlogged branch."""
    from veridex_api import sbr

    resolver = sbr.get_resolver()
    log = sbr.get_log()
    sha = hashlib.sha256(data).hexdigest()
    manifest_id = f"urn:c2pa:b2-{sha}"
    existing = await run_in_threadpool(resolver.get_manifest, manifest_id)
    already_logged = bool(await run_in_threadpool(log.index_for, manifest_id))
    if existing is not None and already_logged:
        record_idempotent_register()  # dedup evidence: answered from the existing record
        return existing, True  # true idempotent redelivery: registered AND proven
    # Use the registered manifest's hash on a heal so the proof matches the registered record.
    manifest = existing or Manifest(
        manifest_id=manifest_id,
        asset_sha256=sha,
        created_at=datetime.now(UTC).isoformat(),
        system_provenance={"source": source, "bucket": bucket, "objectKey": object_key},
        soft_bindings=[SoftBinding(alg=ALG_TRUSTMARK_P, value=f"B2{sha[:10]}")],
    )
    if existing is None:
        await run_in_threadpool(resolver.register, manifest, image, f"B2{sha[:10]}")
    if not already_logged:
        # Fail loudly on an append failure (matches /ingest): the asset is recoverable but has no
        # inclusion proof. A redelivery (or a register retry) heals it via the branch above.
        try:
            await run_in_threadpool(log.append, manifest_id, manifest.canonical_hash())
        except Exception as exc:  # noqa: BLE001 - surface it; never return ok with no proof
            logger.error("b2 ingest: %s registered, log append failed: %s", manifest_id, exc)
            raise HTTPException(
                status_code=500, detail="manifest registered but log append failed"
            ) from exc
    return manifest, False


async def _ingest_events(events: list[Any]) -> tuple[int, int]:
    """Fetch + register each ObjectCreated event under the watched prefix. Returns (ingested,
    skipped). Every per-event failure is caught: one bad object must not fail the whole webhook."""
    from veridex_api import sbr

    storage = sbr.get_storage()
    prefix = _watch_prefix()
    expected_bucket = _expected_bucket()
    ingested = 0
    skipped = 0
    for ev in events:
        if not isinstance(ev, dict):
            skipped += 1
            continue
        name = str(ev.get("objectName", ""))
        et = str(ev.get("eventType", ""))
        bucket = str(ev.get("bucketName", ""))
        size = ev.get("objectSize")
        # Hard gate BEFORE any fetch: only ObjectCreated, our bucket, our prefix, and a declared
        # size that is a valid bounded int (a missing/negative/oversized size never reaches B2).
        if (
            not et.startswith("b2:ObjectCreated")
            or not name.startswith(prefix)
            or storage is None
            or (expected_bucket is not None and bucket != expected_bucket)
            or not isinstance(size, int)
            or size < 0
            or size > _MAX_OBJECT_BYTES
        ):
            skipped += 1
            continue
        try:
            data = await run_in_threadpool(storage.get, name)
        except Exception as exc:  # noqa: BLE001 - a fetch failure must not 500 the webhook
            logger.warning("b2-event: fetch failed for %s: %s", name, exc)
            skipped += 1
            continue
        if len(data) > _MAX_OBJECT_BYTES:  # backstop if the declared size lied
            skipped += 1
            continue
        try:
            image = await anyio.to_thread.run_sync(
                sbr._decode_image, data, limiter=sbr._image_decode_limiter
            )
        except Exception as exc:  # noqa: BLE001 - not a decodable image; skip, never 500
            logger.info("b2-event: %s is not a decodable image (%s); skipping", name, exc)
            skipped += 1
            continue
        # The shared register core (also used by the BYO direct-upload path). A log-append failure
        # raises HTTPException(500) out of the webhook, matching /ingest: never ok with no proof.
        manifest, already_registered = await ingest_stored_object(
            name, bucket, data, image, source="b2-event-ingest"
        )
        if already_registered:
            skipped += 1  # true idempotent redelivery: registered AND proven
            continue
        _record(
            {
                "objectKey": name,
                "manifestId": manifest.manifest_id,
                "bucket": bucket,
                "sizeBytes": len(data),
                "ingestedAt": manifest.created_at,
            }
        )
        ingested += 1
    return ingested, skipped


@router.post("/webhooks/b2-event", include_in_schema=False)
async def b2_event(
    request: Request,
    x_signature: str | None = Header(default=None, alias="X-Bz-Event-Notification-Signature"),
) -> JSONResponse:
    """Receive a Backblaze B2 Event Notification, verify its HMAC signature, and auto-ingest the new
    object(s) for provenance recovery. Refuses unsigned calls; acks B2's connectivity TestEvent."""
    secret = _signing_secret()
    raw = await request.body()
    if secret is None:
        # Not configured: we cannot verify the caller, so we never ingest unsigned. Honest 503.
        return JSONResponse({"status": "not-configured"}, status_code=503)
    if not _verify_signature(raw, x_signature, secret):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="malformed payload") from exc

    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        if isinstance(payload, dict) and payload.get("eventType") == "b2:TestEvent":
            return JSONResponse({"status": "test-ok"})
        events = []
    # Bound the list FIRST so neither the TestEvent scan nor ingestion can do O(n) work on a huge,
    # validly-signed payload. (The body is also size-capped by the request-body middleware.)
    if len(events) > _MAX_EVENTS_PER_REQUEST:
        raise HTTPException(status_code=413, detail="too many events in one notification")
    if any(isinstance(e, dict) and e.get("eventType") == "b2:TestEvent" for e in events):
        return JSONResponse({"status": "test-ok"})

    ingested, skipped = await _ingest_events(events)
    return JSONResponse({"status": "ok", "ingested": ingested, "skipped": skipped})


@router.get("/demo/b2-events", response_model=B2EventStatus, include_in_schema=False)
async def b2_events_status() -> B2EventStatus:
    """The B2 event-driven ingest surface: whether the webhook is configured, the watched prefix,
    and the most recently auto-ingested objects (each recoverable via /matches/byContent)."""
    with _recent_lock:
        recent = [B2IngestRecord(**r) for r in _recent]
    return B2EventStatus(
        configured=_signing_secret() is not None,
        watch_prefix=_watch_prefix(),
        count=len(recent),
        recent=recent,
    )
