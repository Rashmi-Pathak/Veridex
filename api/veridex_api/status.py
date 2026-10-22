"""A live, judge-facing status surface.

GET /status aggregates the real, currently-true state of the running service: the transparency tree
(size, root, signed-checkpoint epoch, the public key and its source), the storage backend and
whether the demo asset is actually present, the advertised soft-binding algorithms, the live
generation configuration and caps, and a LIVE recovery self-test (it recovers the seeded asset
through the resolver right now and reports the similarity and latency). Every number is measured at
request time, not hardcoded, so the page is a real production-readiness signal, not a claim.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import time

from fastapi import APIRouter
from PIL import Image
from starlette.concurrency import run_in_threadpool

from veridex_api import generate, sbr
from veridex_api.demo import demo_sample_bytes
from veridex_provenance.models import ALG_TRUSTMARK_P, CamelModel
from veridex_storage.storage import B2Storage, asset_key

router = APIRouter()
logger = logging.getLogger(__name__)


class TransparencyStatus(CamelModel):
    tree_size: int
    root_hash: str
    checkpoint_epoch: int
    key_source: str
    public_key_hex: str


class StorageStatus(CamelModel):
    backend: str  # "backblaze-b2" | "in-memory" | "none"
    bucket: str | None
    demo_asset_present: bool


class GenerationStatus(CamelModel):
    enabled: bool
    configured: bool
    per_ip_per_day: int
    global_per_day: int
    max_in_flight: int


class RecoverySelfTest(CamelModel):
    """A live recovery of the seeded asset, measured at request time: a real proof the loop runs."""

    recovered: bool
    manifest_id: str | None
    similarity_score: int | None
    latency_ms: int


class StatusResponse(CamelModel):
    service: str
    transparency: TransparencyStatus
    storage: StorageStatus
    recovery_index: str  # "postgres+hnsw" | "postgres+bitcount" | "in-memory"
    algorithms: dict[str, list[str]]
    generation: GenerationStatus
    recovery_self_test: RecoverySelfTest


def _storage_status() -> StorageStatus:
    storage = sbr.get_storage()
    if storage is None:
        return StorageStatus(backend="none", bucket=None, demo_asset_present=False)
    is_b2 = isinstance(storage, B2Storage)
    bucket = os.environ.get("B2_BUCKET_DEV") if is_b2 else None
    sha = hashlib.sha256(demo_sample_bytes()).hexdigest()
    try:
        present = storage.exists(asset_key(sha))
    except Exception as exc:  # noqa: BLE001 - a storage probe must not fail the status page
        logger.warning("status storage probe failed: %s", exc)
        present = False
    return StorageStatus(
        backend="backblaze-b2" if is_b2 else "in-memory", bucket=bucket, demo_asset_present=present
    )


def _recovery_self_test() -> RecoverySelfTest:
    """Recover the seeded asset through the live resolver and report similarity + latency. Measured,
    not asserted; if the demo is not seeded it honestly reports recovered=false."""
    try:
        image = Image.open(io.BytesIO(demo_sample_bytes())).convert("RGB")
        start = time.perf_counter()
        result = sbr.get_resolver().resolve_by_content(image)
        latency_ms = round((time.perf_counter() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 - the self-test is best-effort and never breaks the page
        logger.warning("status recovery self-test failed: %s", exc)
        return RecoverySelfTest(
            recovered=False, manifest_id=None, similarity_score=None, latency_ms=0
        )
    match = result.matches[0] if result.matches else None
    return RecoverySelfTest(
        recovered=match is not None,
        manifest_id=match.manifest_id if match else None,
        similarity_score=match.similarity_score if match else None,
        latency_ms=latency_ms,
    )


_CACHE_TTL_SECONDS = 5.0
_cache: tuple[float, StatusResponse] | None = None


def reset_status_cache() -> None:
    """Clear the status cache (tests, or to force an immediate fresh read)."""
    global _cache
    _cache = None


@router.get("/status", include_in_schema=False)
async def status() -> StatusResponse:
    """A live snapshot of the running service for the judges page. Every value is measured now, then
    cached briefly so a flood cannot hammer the B2 existence probe or re-run the PDQ self-test on
    every request."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    log = sbr.get_log()
    _rows, size, root = await run_in_threadpool(log.snapshot)
    cfg = generate.config()
    resp = StatusResponse(
        service="veridex-api",
        transparency=TransparencyStatus(
            tree_size=size,
            root_hash=root.hex(),
            checkpoint_epoch=size,  # the epoch is the tree size (a signed head per state)
            key_source=sbr._key_source,
            public_key_hex=sbr._public_key_hex(),
        ),
        storage=await run_in_threadpool(_storage_status),
        recovery_index=sbr.get_resolver().index_kind(),
        algorithms={"watermarks": [ALG_TRUSTMARK_P], "fingerprints": []},
        generation=GenerationStatus(
            enabled=cfg["enabled"],
            configured=cfg["configured"],
            per_ip_per_day=cfg["per_ip_per_day"],
            global_per_day=cfg["global_per_day"],
            max_in_flight=cfg["max_in_flight"],
        ),
        recovery_self_test=await run_in_threadpool(_recovery_self_test),
    )
    _cache = (now, resp)
    return resp
