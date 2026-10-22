"""Live, rate-limited generation: the judge-driven loop.

POST /demo/generate runs the real generation side of the loop on a visitor's own prompt. Genblaze
generates an image; Rooted signs its manifest (COSE), indexes it for recovery (PDQ on the lean
deploy, where the watermarker stays the fake), appends it to the Merkle transparency log, and writes
it durably to Backblaze B2. The response carries the image and its signed, logged manifest, so the
UI can show the credentialed asset, let the visitor strip it (an in-browser re-encode or a
screenshot), and recover it through POST /matches/byContent.

The endpoint spends real money (a Genblaze provider call), so it is hard-capped: a per-IP daily
limit, a global daily limit (a true ceiling on provider attempts: an attempt is a potential spend,
so it is never refunded), and an in-flight concurrency cap, all in-memory (the deploy is a single
instance). Every exhaustion or failure path serves the seeded demo asset, labeled, so the loop
always closes: a spent budget, a busy generator, a disabled deploy, or a provider error all return
the seed (a real prior Genblaze image that is itself registered for recovery), never a hard error.
The body is read with a hard size cap before any work, so a large unauthenticated request cannot
exhaust memory. Recovery uses the nearest PDQ fingerprint, and in the live flow the visitor recovers
their own freshly generated asset, which is by construction the nearest match.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from PIL import Image
from starlette.concurrency import run_in_threadpool

from veridex_api import sbr
from veridex_api.demo import (
    DEMO_MANIFEST_ID,
    DEMO_WATERMARK_ID,
    demo_sample_bytes,
    primary_manifest,
)
from veridex_provenance.models import (
    ALG_TRUSTMARK_P,
    CamelModel,
    Manifest,
    SoftBinding,
    canonical_json,
)
from veridex_provenance.signing import sign_manifest
from veridex_storage.storage import Storage, asset_key, manifest_key, signature_key

logger = logging.getLogger(__name__)
router = APIRouter()

_PROMPT_MAX = 500
# A prompt is at most _PROMPT_MAX characters, so 16 KiB covers the JSON envelope. The body is
# streamed and rejected the moment it exceeds this, before it is materialized, so a large or
# Content-Length-lying request on this public, unauthenticated endpoint cannot exhaust memory.
_MAX_BODY_BYTES = 16 * 1024


# --- the generation backend (real Genblaze when keyed, else None -> the endpoint serves the seed) -

_generator: Any | None = None
_generator_built = False
_generator_lock = threading.Lock()


def _build_generator() -> Any:
    """Build the real generation backend, or None when none is configured. A live deploy sets
    GMI_CLOUD_API_KEY and installs the genblaze extra, giving the real Genblaze multi-provider
    generator (GMICloud primary, OpenAI cross-provider fallback). With no key, or with the genblaze
    extra absent, this returns None and the endpoint serves the seeded asset (a real prior Genblaze
    image), so a misconfigured deploy never presents a synthetic placeholder as a generation. Tests
    inject a generator via set_generator, bypassing this. The generator (and its SSRF-hardened asset
    fetch) lives in the worker package."""
    gmi_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_key:
        return None
    try:
        import genblaze_core  # noqa: F401  # the genblaze extra must be installed for live gen
    except ImportError:
        logger.warning(
            "GMI_CLOUD_API_KEY is set but the genblaze extra is not installed; live generation is "
            "off and the endpoint will serve the seeded asset"
        )
        return None
    from veridex_worker.generator import GenblazeGenerator

    fallbacks = [
        m.strip() for m in os.environ.get("VERIDEX_GMI_FALLBACK_MODELS", "").split(",") if m.strip()
    ]
    return GenblazeGenerator(
        gmi_key,
        gmi_model=os.environ.get("VERIDEX_GMI_MODEL", "seedream-5.0-lite"),
        gmi_fallback_models=fallbacks,
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )


def get_generator() -> Any:
    global _generator, _generator_built
    if not _generator_built:
        with _generator_lock:
            if not _generator_built:
                _generator = _build_generator()
                _generator_built = True
    return _generator


def set_generator(generator: Any | None) -> None:
    """Override the generator (tests inject a fake or a failing one). None rebuilds on next use."""
    global _generator, _generator_built
    _generator = generator
    _generator_built = generator is not None


def _recoverable_gen_errors() -> tuple[type[Exception], ...]:
    """Generation failures that justify a labeled fallback to the seeded asset, as opposed to a bug
    that must propagate (and surface as a 500). AssetFetchError is always importable; httpx and
    genblaze errors are added only when those optional deps are installed (the lean deploy may have
    neither), so this never hard-depends on the genblaze extra."""
    from veridex_worker.generator import AssetFetchError

    types: list[type[Exception]] = [AssetFetchError]
    try:
        import httpx

        types.append(httpx.HTTPError)
    except ImportError:
        pass
    try:
        from genblaze_core import GenblazeError

        types.append(GenblazeError)
    except ImportError:
        pass
    return tuple(types)


# --- the cost guard: in-memory daily + concurrency caps (single instance, so in-process is truth) -


@dataclass
class _Decision:
    ok: bool
    reason: str = ""  # "ip" | "global" | "busy" when not ok


class _RateLimiter:
    """In-memory daily and concurrency caps for the paid generation endpoint.

    The deploy is one Render web service, so an in-process counter is the whole truth. Daily counts
    reset at UTC midnight. acquire() reserves a per-IP slot, a global slot, and an in-flight slot
    together; release() frees only the in-flight slot. There is deliberately no refund: an acquired
    slot is a potential provider spend (the provider can bill before any later step fails), so the
    global daily counter is a hard ceiling on provider ATTEMPTS, never rolled back. The per-IP and
    global counters cannot be exceeded under concurrency because acquire() does every check and
    increment under one lock.
    """

    def __init__(self, per_ip_per_day: int, global_per_day: int, max_in_flight: int) -> None:
        self._per_ip = per_ip_per_day
        self._global = global_per_day
        self._max_in_flight = max_in_flight
        self._lock = threading.Lock()
        self._day = ""
        self._ip_counts: dict[str, int] = {}
        self._global_count = 0
        self._in_flight = 0

    def _roll(self, day: str) -> None:
        if day != self._day:
            self._day = day
            self._ip_counts = {}
            self._global_count = 0
            # _in_flight is deliberately NOT reset: a request still running across midnight keeps
            # its slot until it releases, so the concurrency cap holds through the boundary.

    def acquire(self, ip: str, day: str) -> _Decision:
        with self._lock:
            self._roll(day)
            if self._in_flight >= self._max_in_flight:
                return _Decision(False, "busy")
            if self._global_count >= self._global:
                return _Decision(False, "global")
            if self._ip_counts.get(ip, 0) >= self._per_ip:
                return _Decision(False, "ip")
            self._ip_counts[ip] = self._ip_counts.get(ip, 0) + 1
            self._global_count += 1
            self._in_flight += 1
            return _Decision(True)

    def release(self) -> None:
        with self._lock:
            if self._in_flight > 0:
                self._in_flight -= 1


def _build_limiter() -> _RateLimiter:
    return _RateLimiter(
        per_ip_per_day=int(os.environ.get("VERIDEX_GEN_PER_IP_DAY", "5")),
        global_per_day=int(os.environ.get("VERIDEX_GEN_GLOBAL_DAY", "50")),
        max_in_flight=int(os.environ.get("VERIDEX_GEN_MAX_INFLIGHT", "2")),
    )


_limiter = _build_limiter()


def reset_limiter() -> None:
    """Rebuild the limiter from the environment. Tests use this to set caps between cases."""
    global _limiter
    _limiter = _build_limiter()


def _enabled() -> bool:
    """Live generation is opt-in. Off by default so a deploy never spends a provider budget (or
    exposes the network path) until VERIDEX_LIVE_GENERATE=1 is set explicitly."""
    return os.environ.get("VERIDEX_LIVE_GENERATE") == "1"


def config() -> dict[str, Any]:
    """A non-secret snapshot of the generation configuration for the status surface: whether live
    generation is enabled and configured, and the current caps. Exposes no key or provider."""
    return {
        "enabled": _enabled(),
        "configured": get_generator() is not None,
        "per_ip_per_day": _limiter._per_ip,
        "global_per_day": _limiter._global,
        "max_in_flight": _limiter._max_in_flight,
    }


def _client_ip(request: Request) -> str:
    """The caller's IP for per-visitor rate limiting. Render terminates TLS at a proxy and sets
    X-Forwarded-For, so trust its left-most entry (the original client) when present, else the
    socket peer. This is a coarse fairness cap, not an authorization boundary: a spoofed header only
    lets one abuser spread across keys, and the global daily cap (checked independent of IP) is the
    real cost ceiling, so a spoofed IP cannot drive spend past the global budget."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


# --- request body (read with a hard size cap) and the response model ------------------------------


async def _read_prompt(request: Request) -> str:
    """Read the JSON body with a hard streaming byte cap, then extract the prompt. Counting bytes as
    they stream and rejecting at the cap bounds memory the moment the body exceeds the limit, before
    it is fully materialized, regardless of a lying or absent Content-Length. The prompt itself is
    validated (non-empty, length) by the caller."""
    total = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="request body too large")
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        payload = json.loads(body) if body else {}
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), str):
        raise HTTPException(status_code=400, detail="prompt must be a string")
    return str(payload["prompt"])


class GenerateResponse(CamelModel):
    """The generated (or seeded) asset and its signed, logged manifest. The UI shows the image, then
    strips it and recovers it through /matches/byContent. fell_back_to_seed is true when the asset
    is the seeded demo asset (generation disabled, the budget spent, the generator busy, or a
    provider error), with reason explaining why, so the UI never presents a fallback as a fresh
    generation. merkle_index is the 0-based transparency-log leaf, or -1 when the asset is not
    logged."""

    image: str  # a data: URL (image/jpeg)
    manifest_id: str
    watermark_id: str
    merkle_index: int
    model: str
    provider: str
    signature_b64: str
    manifest: dict[str, Any]  # the redacted manifest (camelCase), for display
    stored_on_b2: bool
    fell_back_to_seed: bool
    reason: str | None = None


def _is_b2(storage: Storage) -> bool:
    from veridex_storage.storage import B2Storage

    return isinstance(storage, B2Storage)


def _seed_response(reason: str) -> GenerateResponse:
    """The seeded demo asset as a generation result, labeled honestly. Used on every exhaustion or
    failure path (disabled, budget spent, busy, provider error). The seed is registered for recovery
    when the demo is seeded (VERIDEX_DEMO_SEED=1, the default in production), so the UI can still
    strip this asset and recover it to VERIFIED; the loop closes either way. merkle_index is -1 when
    the demo is not actually in the log, an honest signal rather than a fabricated leaf 0."""
    born = demo_sample_bytes()
    manifest = primary_manifest()
    disclosed = manifest.redacted()
    # Sign the DISCLOSED manifest so this response's signature verifies against the manifest it
    # carries (the primary asset keeps a prompt in system_provenance, which redacted() withholds).
    # The authoritative, transparency-anchored signature over the FULL manifest is served at
    # /demo/signed-manifest; this fallback response stays internally consistent on its own.
    cose = sign_manifest(disclosed, sbr._signing_key)
    storage = sbr.get_storage()
    idx = sbr.get_log().index_for(DEMO_MANIFEST_ID)
    sysprov = manifest.system_provenance
    return GenerateResponse(
        image="data:image/jpeg;base64," + base64.b64encode(born).decode(),
        manifest_id=DEMO_MANIFEST_ID,
        watermark_id=DEMO_WATERMARK_ID,
        merkle_index=(idx - 1) if idx else -1,
        model=str(sysprov.get("model", "seedream-5.0-lite")),
        provider=str(sysprov.get("provider", "gmicloud-image")),
        signature_b64=base64.b64encode(cose).decode(),
        manifest=disclosed.model_dump(by_alias=True),
        stored_on_b2=storage is not None and _is_b2(storage),
        fell_back_to_seed=True,
        reason=reason,
    )


def _generate_and_register(prompt: str) -> GenerateResponse:
    """Synchronous (run in a threadpool): generate, sign, index, log, then store. The exact JPEG
    bytes that are served are the bytes that are hashed, PDQ-indexed, and returned, so recovery
    self-matches with maximum margin after the visitor strips them. Registration and the log append
    run BEFORE the durable B2 write, and the B2 write is best-effort, so a transient storage failure
    can never discard a paid, signed, recoverable generation: the asset stays recoverable from the
    index and stored_on_b2 reports the truth."""
    gen = get_generator().generate(prompt)
    buf = io.BytesIO()
    gen.image.convert("RGB").save(buf, "JPEG", quality=90)
    born = buf.getvalue()
    sha = hashlib.sha256(born).hexdigest()
    # A unique watermark id. The watermarker stays the fake on the lean deploy (recovery is PDQ), so
    # the id is not length-constrained here; a full uuid avoids any birthday collision in the
    # binding index. When real TrustMark variant P (5-char capacity) is wired, the scheme changes.
    watermark_id = "L" + uuid4().hex

    manifest = Manifest(
        manifest_id=f"urn:c2pa:{uuid4()}",
        asset_sha256=sha,
        created_at=datetime.now(UTC).isoformat(),
        system_provenance={"model": gen.model, "provider": gen.provider, "generator": "genblaze"},
        personal_provenance={"prompt": prompt},
        soft_bindings=[SoftBinding(alg=ALG_TRUSTMARK_P, value=watermark_id)],
    )
    cose = sign_manifest(manifest, sbr._signing_key)

    # Make the asset recoverable FIRST (index + log), so a later storage failure cannot orphan it.
    sbr.get_resolver().register(manifest, Image.open(io.BytesIO(born)), watermark_id)
    try:
        index = sbr.get_log().append(manifest.manifest_id, manifest.canonical_hash())
    except Exception as exc:  # noqa: BLE001 - surface the partial state, do not 500 opaquely
        # The manifest is registered (recoverable by content) but not in the transparency log, so it
        # has no inclusion proof. Mirror /ingest: tell the caller exactly that.
        logger.error(
            "manifest %s registered but transparency append failed: %s", manifest.manifest_id, exc
        )
        raise HTTPException(
            status_code=500, detail="manifest registered but transparency log append failed"
        ) from exc

    # Durable B2 write LAST and best-effort: a storage hiccup must not discard a paid, recoverable,
    # signed generation. The asset stays recoverable from the in-memory index; stored_on_b2 is true.
    storage = sbr.get_storage()
    stored = False
    if storage is not None:
        try:
            storage.put(asset_key(sha), born)
            storage.put(manifest_key(manifest.manifest_id), canonical_json(manifest.model_dump()))
            storage.put(signature_key(manifest.manifest_id), cose)
            stored = _is_b2(storage)
        except Exception as exc:  # noqa: BLE001 - any storage backend error; keep the loop closeable
            logger.warning(
                "B2 write failed for %s; the asset stays recoverable in-memory: %s",
                manifest.manifest_id,
                exc,
            )
            stored = False

    return GenerateResponse(
        image="data:image/jpeg;base64," + base64.b64encode(born).decode(),
        manifest_id=manifest.manifest_id,
        watermark_id=watermark_id,
        merkle_index=index - 1,  # append returns the 1-based position; the API is 0-based
        model=gen.model,
        provider=gen.provider,
        signature_b64=base64.b64encode(cose).decode(),
        manifest=manifest.redacted().model_dump(by_alias=True),
        stored_on_b2=stored,
        fell_back_to_seed=False,
    )


@router.post("/demo/generate", response_model=GenerateResponse, include_in_schema=False)
async def demo_generate(request: Request) -> GenerateResponse:
    """Generate on a visitor's prompt, register the result for recovery, and return the credentialed
    asset. Hard-capped (per-IP/day, global/day, in-flight) because it spends a provider call. Every
    exhaustion or failure path serves the seeded asset, labeled, so the loop always closes."""
    prompt = (await _read_prompt(request)).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt must not be empty")
    if len(prompt) > _PROMPT_MAX:
        raise HTTPException(status_code=400, detail=f"prompt exceeds {_PROMPT_MAX} characters")

    if not _enabled():
        return _seed_response("live generation is not enabled on this deploy")
    if get_generator() is None:
        return _seed_response("live generation is not configured on this deploy")

    day = datetime.now(UTC).date().isoformat()
    ip = _client_ip(request)
    decision = _limiter.acquire(ip, day)
    if not decision.ok:
        # Exhaustion serves the seed (a real, recoverable asset), not a hard error, so the live-loop
        # panel never breaks during judging: the visitor can still strip and recover the seed.
        reason = {
            "busy": "the live generator is busy; showing the seeded asset",
            "global": "the daily generation budget is reached; showing the seeded asset",
            "ip": "the per-visitor generation limit is reached; showing the seeded asset",
        }[decision.reason]
        return _seed_response(reason)
    try:
        return await run_in_threadpool(_generate_and_register, prompt)
    except _recoverable_gen_errors() as exc:
        # A provider/network/asset failure is not the visitor's fault. The global slot stays
        # consumed (the provider may have billed before failing, so the cost ceiling must count this
        # attempt), and we serve the seed so the loop still closes. A non-recoverable error (a bug)
        # is not in this tuple, so it propagates and surfaces as a 500 rather than being masked.
        logger.warning("live generation failed (%s); falling back to the seeded asset", exc)
        return _seed_response("the generation provider is unavailable; showing the seeded asset")
    finally:
        _limiter.release()
