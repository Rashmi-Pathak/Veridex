"""The vendor-neutral C2PA Soft Binding Resolution API (C2PA v2.4 route shapes).

The resolver uses the Postgres index when DATABASE_URL is set and the in-memory index otherwise, so
the recovery path runs end to end with or without credentials. The B2 store and the TrustMark
watermarker swap in at the same seams. The /ingest route is a convenience for the demo; the spec
query routes are byContent and byBinding.

Response models inherit from CamelModel, so the HTTP surface (and the generated OpenAPI) emit
camelCase aliases, while model_dump() stays snake_case for storage, canonical hashing, and signing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import ipaddress
import logging
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

import anyio
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import Field
from pymerkle import MerkleProof
from starlette.concurrency import run_in_threadpool

from veridex_api.integrity import (
    STAGED_NOTE,
    IntegrityClashResponse,
    compare_provenance,
    load_staged_embedded_summary,
)
from veridex_provenance.audio import AudioDecodeError, audio_to_image
from veridex_provenance.merkle import TransparencyLog, verify_checkpoint
from veridex_provenance.models import (
    ALG_TRUSTMARK_P,
    CamelModel,
    Manifest,
    MerkleCheckpoint,
    SoftBinding,
    SoftBindingQueryResult,
    SupportedAlgorithms,
)
from veridex_provenance.resolver import Index, InMemoryIndex, Resolver
from veridex_provenance.signing import (
    generate_keypair,
    load_private_key,
    public_key_bytes,
    verify_manifest,
)
from veridex_provenance.video import VideoDecodeError, video_frames
from veridex_provenance.watermark import FakeWatermarker, Watermarker
from veridex_storage.storage import Storage

logger = logging.getLogger(__name__)

# Bound the decoder's pixel budget so a small, highly compressible upload cannot expand into
# hundreds of MB on decode. Pillow only raises DecompressionBombError above 2x this; the 1x-2x band
# merely warns and would otherwise proceed, so _decode_image promotes that warning to an error too.
Image.MAX_IMAGE_PIXELS = 64_000_000

router = APIRouter()

# The recovery resolver. It uses PostgresIndex when DATABASE_URL is set, so the live recovery path
# runs on Postgres, and falls back to the in-memory index otherwise so the demo is credential-free.
# Built lazily on first use and overridable for tests (set_resolver). The watermarker stays the fake
# until TrustMark is wired; recovery uses the PDQ path either way.
_resolver: Resolver | None = None

# The transparency log the recovery server serves. /ingest appends each manifest's canonical hash as
# a leaf; the log owns the manifest-id -> leaf-index map. With DATABASE_URL it persists the ordered
# leaves to Postgres and rebuilds the tree on startup, so proofs survive a restart; otherwise it is
# the credential-free in-memory log. Built lazily and overridable for tests (set_log).
_log: TransparencyLog | None = None


def _load_signing_key() -> tuple[Ed25519PrivateKey, str]:
    """The Ed25519 key that signs checkpoints, with its provenance.

    A configured key loads from ED25519_PRIVATE_KEY_HEX (the raw 32-byte key as hex, a single-line
    env-friendly value) or ED25519_PRIVATE_KEY_PATH (a raw-key file). Pinning a stable key across
    redeploys keeps the public key and every inclusion proof valid through the judging window. When
    none is set we fail closed if a key is required (VERIDEX_REQUIRE_SIGNING_KEY=1 or
    APP_ENV=production), so a production tamper-evidence anchor is never silently signed by a
    throwaway key. Otherwise an ephemeral key is generated, and key_source reports "ephemeral" so a
    dev/CI key is never mistaken for a trust anchor.
    """
    hex_key = os.environ.get("ED25519_PRIVATE_KEY_HEX")
    if hex_key:
        return load_private_key(bytes.fromhex(hex_key.strip())), "configured"
    path = os.environ.get("ED25519_PRIVATE_KEY_PATH")
    if path:
        return load_private_key(Path(path).read_bytes()), "configured"
    require = os.environ.get("VERIDEX_REQUIRE_SIGNING_KEY") == "1" or (
        os.environ.get("APP_ENV") == "production"
    )
    if require:
        raise RuntimeError(
            "ED25519_PRIVATE_KEY_HEX or ED25519_PRIVATE_KEY_PATH is required when "
            "VERIDEX_REQUIRE_SIGNING_KEY=1 or APP_ENV=production; refusing to sign checkpoints "
            "with an ephemeral key"
        )
    priv, _pub = generate_keypair()
    return priv, "ephemeral"


_signing_key, _key_source = _load_signing_key()


def _public_key_hex() -> str:
    return str(public_key_bytes(_signing_key.public_key()).hex())


_checkpoint_cache: MerkleCheckpoint | None = None
_checkpoint_cache_lock = threading.Lock()


def _signed_head() -> MerkleCheckpoint:
    """The signed tree head for the current log state. The epoch IS the tree size. A checkpoint is
    signed ONCE per tree state and cached, so the same tree state always yields the same signed
    checkpoint (a GET is idempotent and reproducible) while signed_at is authenticated (bound into
    the signature): re-signing per read would otherwise change the signature every call now that the
    timestamp is signed. A new state (a grown tree) signs a fresh checkpoint."""
    global _checkpoint_cache
    log = get_log()
    with _checkpoint_cache_lock:
        size = log.size
        root_hex = log.root().hex()
        cached = _checkpoint_cache
        if cached is not None and cached.tree_size == size and cached.root_hash == root_hex:
            return cached
        cp = log.checkpoint(size, _signing_key, datetime.now(UTC).isoformat())
        _checkpoint_cache = cp
        return cp


def current_checkpoint() -> MerkleCheckpoint:
    """The current signed tree head (public accessor for the checkpoint-lock surface)."""
    return _signed_head()


def signing_public_key() -> Ed25519PublicKey:
    """The Ed25519 public key that verifies checkpoint signatures."""
    return _signing_key.public_key()


def key_source() -> str:
    """Whether the signing key is a configured anchor or an ephemeral dev key."""
    return _key_source


def _psycopg_url(url: str) -> str:
    """Normalize a SQLAlchemy/async-style URL to the libpq form psycopg expects. DATABASE_URL is
    written for the app's async driver (postgresql+asyncpg://); the sync index needs postgresql://."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def _make_watermarker() -> Watermarker:
    """The recovery watermarker. Defaults to the fake, so recovery runs on the PDQ path and the
    deploy stays lean. Set VERIDEX_REAL_WATERMARK=1 (and install the `watermark` extra) to use the
    real TrustMark variant P; that import pulls torch, so it is opt-in. If the extra is missing we
    fall back to the fake rather than failing the resolver."""
    if os.environ.get("VERIDEX_REAL_WATERMARK") == "1":
        try:
            from veridex_provenance.watermark import TrustMarkWatermarker

            return TrustMarkWatermarker()  # __init__ imports trustmark -> ImportError if absent
        except ImportError:
            # The operator explicitly opted into real watermarking; do not silently degrade to the
            # no-op fake. Warn loudly so the missing `watermark` extra is visible in the logs.
            logger.warning(
                "VERIDEX_REAL_WATERMARK=1 but the trustmark extra is not importable; "
                "falling back to the no-op FakeWatermarker (install the `watermark` extra)"
            )
    return FakeWatermarker()


def _make_resolver() -> Resolver:
    """Build the resolver. DATABASE_URL selects the Postgres index (live recovery on Postgres);
    without it the in-memory index keeps the demo credential-free."""
    url = os.environ.get("DATABASE_URL")
    index: Index = InMemoryIndex()
    if url:
        from veridex_storage.index import PostgresIndex

        pg = PostgresIndex(_psycopg_url(url))
        pg.create_schema()
        index = pg
    return Resolver(index, _make_watermarker())


# Locks for the lazy singletons: routes run in a threadpool (run_in_threadpool), so two concurrent
# first requests could otherwise both build a resolver/log (one pool then leaks). The startup
# lifespan pre-builds both, so this is belt-and-suspenders for paths that skip the lifespan.
_resolver_lock = threading.Lock()
_log_lock = threading.Lock()


def get_resolver() -> Resolver:
    global _resolver
    if _resolver is None:
        with _resolver_lock:
            if _resolver is None:
                _resolver = _make_resolver()
    return _resolver


def set_resolver(resolver: Resolver | None) -> None:
    """Override the resolver, or reset to None to rebuild on next use. Tests use this to point the
    live API at a Postgres-backed resolver."""
    global _resolver
    _resolver = resolver


# A separate resolver for AUDIO so an audio fingerprint can never cross-match an image one: each
# modality keeps its own index. The audio "image" is a spectrogram (see
# veridex_provenance.audio), so the same Resolver/PDQ/Hamming machinery recovers audio with no
# new matcher. Built lazily.
_audio_resolver: Resolver | None = None
_audio_resolver_lock = threading.Lock()


def get_audio_resolver() -> Resolver:
    global _audio_resolver
    if _audio_resolver is None:
        with _audio_resolver_lock:
            if _audio_resolver is None:
                _audio_resolver = Resolver(InMemoryIndex(), FakeWatermarker())
    return _audio_resolver


def set_audio_resolver(resolver: Resolver | None) -> None:
    """Override the audio resolver, or reset to None to rebuild on next use (tests)."""
    global _audio_resolver
    _audio_resolver = resolver


# ffmpeg decode is the one expensive, unauthenticated step in the audio path. Bound how many run at
# once so a burst of audio uploads cannot pin the whole threadpool (and starve every other blocking
# route) for the decode window; excess requests await a token rather than holding a worker.
_audio_decode_limiter = anyio.CapacityLimiter(
    int(os.environ.get("VERIDEX_AUDIO_DECODE_CONCURRENCY", "3"))
)


# A separate resolver for VIDEO (same reasoning as audio): a video registers one PDQ per sampled
# frame in its own index, so video frames never cross-match an image or audio asset. Built lazily.
_video_resolver: Resolver | None = None
_video_resolver_lock = threading.Lock()
_video_decode_limiter = anyio.CapacityLimiter(
    int(os.environ.get("VERIDEX_VIDEO_DECODE_CONCURRENCY", "2"))
)


def get_video_resolver() -> Resolver:
    global _video_resolver
    if _video_resolver is None:
        with _video_resolver_lock:
            if _video_resolver is None:
                _video_resolver = Resolver(InMemoryIndex(), FakeWatermarker())
    return _video_resolver


def set_video_resolver(resolver: Resolver | None) -> None:
    """Override the video resolver, or reset to None to rebuild on next use (tests)."""
    global _video_resolver
    _video_resolver = resolver


def _lookup_manifest(manifest_id: str) -> Manifest | None:
    """Find a manifest across all modality resolvers (image, audio, video). They keep separate
    indexes so fingerprints never cross-match, but a manifest recovered from any of them must still
    be fetchable by id (for GET /manifests and the inclusion proof)."""
    for resolver in (get_resolver(), get_audio_resolver(), get_video_resolver()):
        manifest = resolver.get_manifest(manifest_id)
        if manifest is not None:
            return manifest
    return None


def _make_log() -> TransparencyLog:
    """Build the transparency log. DATABASE_URL persists the ordered leaves to Postgres (so proofs
    survive a restart and a second instance); without it the leaves live in memory."""
    url = os.environ.get("DATABASE_URL")
    if url:
        from veridex_storage.transparency import PostgresTransparencyStore

        return TransparencyLog(PostgresTransparencyStore(_psycopg_url(url)))
    return TransparencyLog()


def get_log() -> TransparencyLog:
    global _log
    if _log is None:
        with _log_lock:
            if _log is None:
                _log = _make_log()
    return _log


def set_log(log: TransparencyLog | None) -> None:
    """Override the transparency log, or reset to None to rebuild on next use (tests)."""
    global _log
    _log = log


# The B2 object store. When the B2 credentials are present (B2_KEY_ID, B2_APP_KEY, B2_BUCKET_DEV),
# Rooted stores assets, manifests, and signatures content-addressably on Backblaze B2; without them
# the demo runs in-memory and never touches B2. Built lazily, overridable for tests (set_storage).
_storage: Storage | None = None
_storage_built = False
_storage_lock = threading.Lock()


def _make_storage() -> Storage | None:
    key_id = os.environ.get("B2_KEY_ID")
    app_key = os.environ.get("B2_APP_KEY")
    bucket = os.environ.get("B2_BUCKET_DEV")
    if not (key_id and app_key and bucket):
        return None
    from veridex_storage.storage import B2Storage

    return B2Storage(key_id, app_key, bucket)


def get_storage() -> Storage | None:
    global _storage, _storage_built
    if not _storage_built:
        with _storage_lock:
            if not _storage_built:
                _storage = _make_storage()
                _storage_built = True
    return _storage


def set_storage(storage: Storage | None) -> None:
    """Override the object store (tests). Marks it built so get_storage returns it as-is."""
    global _storage, _storage_built
    _storage = storage
    _storage_built = True


# A SEPARATE Object-Lock-enabled bucket for the signed Merkle checkpoints. Kept distinct from the
# iteration bucket (B2_BUCKET_DEV) because a fileLock-enabled bucket's compliance-retained writes
# are immutable: you iterate against the dev bucket and write the audit anchor to the locked one.
# When B2_BUCKET_LOCKED is unset, the checkpoint demo falls back to the in-memory model, labeled.
_locked_storage: Storage | None = None
_locked_storage_built = False


def _make_locked_storage() -> Storage | None:
    key_id = os.environ.get("B2_KEY_ID")
    app_key = os.environ.get("B2_APP_KEY")
    bucket = os.environ.get("B2_BUCKET_LOCKED")
    if not (key_id and app_key and bucket):
        return None
    from veridex_storage.storage import B2Storage

    return B2Storage(key_id, app_key, bucket)


def get_locked_storage() -> Storage | None:
    """The Object-Lock checkpoint bucket, or None when B2_BUCKET_LOCKED is not configured."""
    global _locked_storage, _locked_storage_built
    if not _locked_storage_built:
        with _storage_lock:
            if not _locked_storage_built:
                _locked_storage = _make_locked_storage()
                _locked_storage_built = True
    return _locked_storage


def set_locked_storage(storage: Storage | None) -> None:
    """Override the locked checkpoint store (tests)."""
    global _locked_storage, _locked_storage_built
    _locked_storage = storage
    _locked_storage_built = True


_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # cap on an uploaded asset

# Bound concurrent image decodes like audio/video are bounded: _decode_image can materialize up to
# ~192 MB of RGB (Image.MAX_IMAGE_PIXELS), so an unbounded burst on the public byContent/ingest
# routes could OOM the lean instance. Excess requests await a token rather than pinning a worker.
_image_decode_limiter = anyio.CapacityLimiter(
    int(os.environ.get("VERIDEX_IMAGE_DECODE_CONCURRENCY", "4"))
)


def _decode_image(data: bytes) -> Image.Image:
    """Decode uploaded bytes to an RGB image, failing closed on untrusted input. An oversized upload
    is rejected (413) before decode; anything that is not a decodable image, including a
    decompression bomb whose header declares a huge size, becomes a 415 rather than a 500.

    The bomb check reads the declared pixel size from the header (Image.open is lazy) and rejects
    before materializing pixels with .convert(). This is an explicit, thread-safe check: it does not
    touch the process-global warnings filters, so it is safe under the multi-thread decode pool
    (mutating warnings filters there could let a concurrent decode slip a bomb through).
    DecompressionBombError is not an OSError, so it is caught explicitly."""
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="uploaded asset too large")
    try:
        img = Image.open(io.BytesIO(data))
        width, height = img.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        raise HTTPException(status_code=415, detail="invalid or unsupported image") from exc
    max_pixels = Image.MAX_IMAGE_PIXELS
    if max_pixels is not None and width * height > max_pixels:
        raise HTTPException(status_code=415, detail="invalid or unsupported image")
    try:
        return img.convert("RGB")
    except (OSError, Image.DecompressionBombError, ValueError) as exc:
        raise HTTPException(status_code=415, detail="invalid or unsupported image") from exc


async def _read_image(file: UploadFile) -> Image.Image:
    # Offload the CPU/memory-bound decode off the event loop so a large (or bomb) image cannot stall
    # request handling for every other client, and bound concurrency (like the audio/video decoders)
    # so a burst of large decodes cannot pin the threadpool or OOM the instance.
    data = await file.read()
    return await anyio.to_thread.run_sync(_decode_image, data, limiter=_image_decode_limiter)


def _check_ingest_auth(provided: str | None) -> None:
    """Gate the /ingest write path. VERIDEX_INGEST_KEY, when set, must match the X-Ingest-Key header
    (constant-time). When it is unset, ingest is allowed in the credential-free demo but fails
    closed in production (APP_ENV=production or VERIDEX_REQUIRE_INGEST_KEY=1), mirroring the
    signing-key fail-closed pattern, so a public deploy never exposes an unauthenticated writer."""
    expected = os.environ.get("VERIDEX_INGEST_KEY")
    if expected:
        # Compare as bytes: hmac.compare_digest raises on a non-ASCII str, which would turn a
        # crafted header into a 500 instead of a clean 401. Encoding sidesteps that (still fails
        # closed regardless), keeping the comparison constant-time.
        ok = provided is not None and hmac.compare_digest(
            provided.encode("utf-8"), expected.encode("utf-8")
        )
        if not ok:
            raise HTTPException(status_code=401, detail="invalid or missing ingest credential")
        return
    require = (
        os.environ.get("VERIDEX_REQUIRE_INGEST_KEY") == "1"
        or os.environ.get("APP_ENV") == "production"
    )
    if require:
        raise HTTPException(
            status_code=503, detail="ingest is disabled: VERIDEX_INGEST_KEY is not configured"
        )


# manifest_id and watermark_id flow into content-addressable storage keys (manifests/<id>.json,
# signatures/<id>.cose) and the soft binding; constrain them to a safe charset at the boundary so a
# value with '/' or '..' can never shape a key (the key builders only sanitize ':').
# \Z (absolute end), not $: $ also matches just before a trailing newline, so "id\n" would pass
# and the newline would flow into a storage key. Matches the BYO key regex's deliberate \Z anchor.
_SAFE_ID_RE = re.compile(r"\A[A-Za-z0-9:_.\-]{1,256}\Z")


def _validate_id(value: str, field: str) -> None:
    if not _SAFE_ID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"invalid {field}")


# --- C2PA SBR 2.4 proof-of-ingestion receipts (spec.c2pa.org .../2.4/softbinding/Decoupled) -------
# A receipt is the spec-shaped, portable wrapper around Rooted's existing Merkle inclusion proof: it
# states that a manifest was ingested into this repository and carries the real, independently
# verifiable proof as its anchor.proof. The receipt routes reuse the SAME proof the
# /transparency/proof route returns (see _inclusion_proof), so a receipt is never a re-derived or
# fabricated proof.
_RECEIPT_TYPE: Literal["org.c2pa.manifest-receipt"] = "org.c2pa.manifest-receipt"
_RECEIPT_CONTEXT: dict[str, str] = {
    "c2pa": "https://c2pa.org/ns/",
    "receipt": "https://c2pa.org/ns/manifest-receipt#",
}


class ReceiptRepository(CamelModel):
    """The repository that ingested the manifest: its base URI and the canonical manifest id."""

    uri: str
    manifest_id: str


class ReceiptAnchor(CamelModel):
    """Where and how the ingestion proof is retrieved and verified. proof is repository-specific
    (the spec marks it additionalProperties true), so Rooted's Merkle inclusion proof is conformant:
    it carries the hash alg, the leaf, the tree head, the audit path, and the signed checkpoint."""

    uri: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    proof: dict[str, Any]


class ManifestReceipt(CamelModel):
    """A C2PA SBR 2.4 c2pa.manifestReceipt: portable proof a manifest was ingested into this
    repository. @context and @type carry the @ literally (FastAPI serializes by alias)."""

    context: dict[str, str] | str = Field(
        default_factory=lambda: dict(_RECEIPT_CONTEXT), alias="@context"
    )
    type_: Literal["org.c2pa.manifest-receipt"] = Field(default=_RECEIPT_TYPE, alias="@type")
    repository: ReceiptRepository
    anchor: ReceiptAnchor


class VerifiedManifestReceipt(ManifestReceipt):
    """A c2pa.verifiedManifestReceipt: a manifestReceipt plus the result of verifying it against the
    transparency log. verified is the real check (the inclusion proof recomputes to the signed root
    and the checkpoint signature verifies under the public key); error states why a verification
    failed, and is omitted when verified is true."""

    verified: bool
    error: str | None = None


class ManifestCreateResult(CamelModel):
    """A c2pa.manifestCreateResult: the ingested manifest id, plus the receipt when it was requested
    via returnReceipt. receipt is omitted otherwise, so the default ingest response is unchanged."""

    manifest_id: str
    receipt: ManifestReceipt | None = None


# Lenient input shapes for POST verifyReceipt: a caller submits a receipt to be checked, so the
# fields are optional here and the verdict (including a wrong @type or a mismatched id) is reported
# as verified=false with an error, not rejected at parse time. A body missing the required receipt
# fields is a malformed body (400).
class ReceiptRepositoryInput(CamelModel):
    uri: str | None = None
    manifest_id: str | None = None


class ReceiptAnchorInput(CamelModel):
    uri: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    proof: dict[str, Any] | None = None


class ManifestReceiptInput(CamelModel):
    context: dict[str, Any] | str | None = Field(default=None, alias="@context")
    type_: str | None = Field(default=None, alias="@type")
    repository: ReceiptRepositoryInput | None = None
    anchor: ReceiptAnchorInput | None = None


@router.get("/services/supportedAlgorithms", response_model=SupportedAlgorithms)
async def supported_algorithms() -> SupportedAlgorithms:
    # Advertise the configured federation peers so the SBR network is discoverable from the spec
    # service-description route.
    return SupportedAlgorithms(peers=_peer_urls())


@router.post(
    "/ingest",
    response_model=ManifestCreateResult,
    response_model_exclude_none=True,
    responses={
        400: {"description": "malformed request body"},
        401: {"description": "invalid or missing ingest credential"},
        409: {"description": "manifest id or watermark id already exists"},
        413: {"description": "uploaded asset too large"},
        415: {"description": "invalid or unsupported image"},
        503: {"description": "ingest disabled (no ingest key configured in production)"},
    },
)
async def ingest(
    request: Request,
    file: UploadFile = File(...),
    manifest_id: str = Form(...),
    watermark_id: str = Form(...),
    model: str = Form("unknown"),
    x_ingest_key: str | None = Header(default=None, alias="X-Ingest-Key"),
    # Typed bool (not bool | None) with a False default so the OpenAPI query param is a non-nullable
    # optional boolean: the schemathesis contract test never feeds it the literal "null". Absent or
    # false leaves the response as {"manifestId": ...} (full back-compat); true adds the receipt.
    return_receipt: bool = Query(
        default=False,
        alias="returnReceipt",
        description=(
            "C2PA SBR optional param: when true, include the manifest receipt so the response "
            "matches c2pa.manifestCreateResult. The receipt is also retrievable at "
            "GET /manifests/{manifestId}/receipts."
        ),
    ),
) -> ManifestCreateResult:
    """Trusted generation-side ingest, gated by VERIDEX_INGEST_KEY (the X-Ingest-Key
    header; required in production). The public query surface is /matches/*.

    The asset hash is computed from the uploaded bytes, never taken from the client. An existing
    manifest id is not overwritten (409), and a watermark id already bound to a manifest cannot be
    re-pointed (409), so a second ingest cannot poison recovery for a victim's watermark.

    The log append is synchronous, so when returnReceipt is true the manifest is already a leaf and
    the receipt (its real inclusion proof) is returned inline; otherwise the response is just the
    manifest id, unchanged.
    """
    auth_key = (
        x_ingest_key
        or request.headers.get("X-Veridex-Ingest-Key")
        or request.headers.get("x-veridex-ingest-key")
    )
    _check_ingest_auth(auth_key)
    _validate_id(manifest_id, "manifest_id")
    _validate_id(watermark_id, "watermark_id")
    resolver = get_resolver()
    # The index calls are synchronous (psycopg); offload them so a DB round-trip never blocks the
    # event loop and serializes concurrent requests.
    if await run_in_threadpool(resolver.get_manifest, manifest_id) is not None:
        raise HTTPException(status_code=409, detail="manifest id already exists")
    existing = await run_in_threadpool(resolver.resolve_by_binding, ALG_TRUSTMARK_P, watermark_id)
    if existing.matches:
        raise HTTPException(status_code=409, detail="watermark id already bound to a manifest")
    data = await file.read()
    image = await anyio.to_thread.run_sync(_decode_image, data, limiter=_image_decode_limiter)
    manifest = Manifest(
        manifest_id=manifest_id,
        asset_sha256=hashlib.sha256(data).hexdigest(),
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": model},
        soft_bindings=[SoftBinding(alg=ALG_TRUSTMARK_P, value=watermark_id)],
    )
    await run_in_threadpool(resolver.register, manifest, image, watermark_id)
    try:
        await run_in_threadpool(get_log().append, manifest_id, manifest.canonical_hash())
    except Exception as exc:  # noqa: BLE001 - surface ANY append failure clearly, not an opaque 500
        # The manifest is registered (recoverable) but not in the transparency log, so it has no
        # inclusion proof yet. Tell the caller exactly that. (A single cross-store transaction is
        # the documented production follow-up.)
        logger.error("manifest %s registered but transparency append failed: %s", manifest_id, exc)
        raise HTTPException(
            status_code=500, detail="manifest registered but transparency log append failed"
        ) from exc
    if return_receipt:
        receipt = await run_in_threadpool(_manifest_receipt, manifest_id, _self_base_url(request))
        return ManifestCreateResult(manifest_id=manifest_id, receipt=receipt)
    return ManifestCreateResult(manifest_id=manifest_id)


def _cap_matches(result: SoftBindingQueryResult, max_results: int | None) -> SoftBindingQueryResult:
    """Cap the matches list to the optional C2PA SBR maxResults param. When it is absent the result
    is returned unchanged (full back-compat); maxResults >= 1 is enforced at the route boundary."""
    if max_results is None or len(result.matches) <= max_results:
        return result
    return SoftBindingQueryResult(matches=result.matches[:max_results])


@router.post(
    "/matches/byContent",
    response_model=SoftBindingQueryResult,
    responses={
        400: {"description": "malformed request body"},
        413: {"description": "uploaded asset too large"},
        415: {"description": "invalid or unsupported image"},
    },
)
async def matches_by_content(
    file: UploadFile = File(...),
    # Typed int (not int | None) so the OpenAPI query param is a non-nullable optional integer: the
    # schemathesis contract test then never feeds it the literal "null" (which FastAPI would 422).
    # The Query default of None still makes it optional; an absent param arrives as None, so
    # _cap_matches leaves the result unchanged (full back-compat).
    max_results: int = Query(
        default=None,
        ge=1,
        alias="maxResults",
        description="C2PA SBR optional param: cap the number of returned matches.",
    ),
    hint_alg: str | None = Query(
        default=None,
        alias="hintAlg",
        description=(
            "C2PA SBR optional param: a soft-binding algorithm name (e.g. com.adobe.trustmark.P) "
            "to aid resolution. With hintValue, the exact binding is tried before the content scan."
        ),
    ),
    hint_value: str | None = Query(
        default=None,
        alias="hintValue",
        description="C2PA SBR optional param: the soft-binding value for the matching hintAlg.",
    ),
) -> SoftBindingQueryResult:
    """Recover a manifest from an uploaded asset by its perceptual content (PDQ).

    The optional C2PA SBR params are honored without changing WHICH manifest an asset resolves to:
    the uploaded asset is ALWAYS matched by its perceptual content. maxResults caps the list.
    hintAlg + hintValue are ADVISORY only: when the supplied binding names a manifest the content
    ALSO matched, that manifest is moved to the front of the list. The hint can never introduce a
    manifest the content did not match, so uploading arbitrary bytes with a known binding value can
    never forge a "recovered by content" result. To recover a manifest from a binding value alone
    (without the asset content), callers use GET /matches/byBinding, which is honestly binding-only.
    """
    resolver = get_resolver()
    # resolve_by_content does blocking DB work and CPU-bound PDQ; offload it off the event loop.
    image = await _read_image(file)
    result = await run_in_threadpool(resolver.resolve_by_content, image)
    if hint_alg is not None and hint_value is not None and result.matches:
        hinted = await run_in_threadpool(resolver.resolve_by_binding, hint_alg, hint_value)
        hinted_ids = {m.manifest_id for m in hinted.matches}
        if any(m.manifest_id in hinted_ids for m in result.matches):
            ordered = [m for m in result.matches if m.manifest_id in hinted_ids]
            ordered += [m for m in result.matches if m.manifest_id not in hinted_ids]
            result = SoftBindingQueryResult(matches=ordered)
    return _cap_matches(result, max_results)


@router.post(
    "/matches/byAudioContent",
    response_model=SoftBindingQueryResult,
    include_in_schema=False,
    responses={
        413: {"description": "uploaded asset too large"},
        415: {"description": "invalid or unsupported audio"},
    },
)
async def matches_by_audio_content(file: UploadFile = File(...)) -> SoftBindingQueryResult:
    """Recover an audio asset's manifest by its perceptual audio fingerprint, the audio analog of
    /matches/byContent. The asset is decoded and reduced to a spectrogram image, then matched in the
    audio index. It is outside the image-oriented SBR spec contract (so it is unlisted), and
    the audio fingerprint stays internal like PDQ."""
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="uploaded asset too large")
    try:
        # Bound concurrent ffmpeg decodes (the limiter), separately from the rest of the threadpool.
        image = await anyio.to_thread.run_sync(audio_to_image, data, limiter=_audio_decode_limiter)
    except AudioDecodeError as exc:
        raise HTTPException(status_code=415, detail="invalid or unsupported audio") from exc
    return await run_in_threadpool(get_audio_resolver().resolve_by_content, image)


# Larger than images/audio (25 MB) but still bounded: a re-encoded demo clip is a few MB, and the
# per-frame decode is independently size-bounded (see veridex_provenance.video), so this caps the
# body buffer without needing a multi-GB allowance.
_MAX_VIDEO_UPLOAD_BYTES = 32 * 1024 * 1024


def _resolve_video_frames(frames: list[Image.Image]) -> SoftBindingQueryResult:
    """Match each sampled frame against the video index; the first frame that resolves wins. Any one
    frame match recovers the video, which is what survives a re-encode that perturbs some frames."""
    resolver = get_video_resolver()
    for frame in frames:
        result = resolver.resolve_by_content(frame)
        if result.matches:
            return result
    return SoftBindingQueryResult()


@router.post(
    "/matches/byVideoContent",
    response_model=SoftBindingQueryResult,
    include_in_schema=False,
    responses={
        413: {"description": "uploaded asset too large"},
        415: {"description": "invalid or unsupported video"},
    },
)
async def matches_by_video_content(file: UploadFile = File(...)) -> SoftBindingQueryResult:
    """Recover a video's manifest by per-keyframe PDQ. The video is decoded to sampled frames; the
    first frame whose fingerprint matches the video index recovers the manifest. Outside the
    image-oriented SBR spec contract (so it is unlisted); the per-frame fingerprint is internal."""
    data = await file.read()
    if len(data) > _MAX_VIDEO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="uploaded asset too large")
    try:
        frames = await anyio.to_thread.run_sync(video_frames, data, limiter=_video_decode_limiter)
    except VideoDecodeError as exc:
        raise HTTPException(status_code=415, detail="invalid or unsupported video") from exc
    return await run_in_threadpool(_resolve_video_frames, frames)


@router.get("/matches/byBinding", response_model=SoftBindingQueryResult)
async def matches_by_binding(
    alg: str,
    value: str,
    # Typed int (not int | None) to keep the OpenAPI query param a non-nullable optional integer, so
    # the schemathesis contract test never sends the literal "null" (which FastAPI would 422). The
    # Query default of None still makes it optional; an absent param arrives as None (no cap).
    max_results: int = Query(
        default=None,
        ge=1,
        alias="maxResults",
        description="C2PA SBR optional param: cap the number of returned matches.",
    ),
) -> SoftBindingQueryResult:
    """Recover a manifest by an exact soft binding (alg + value). The optional C2PA SBR maxResults
    param caps the returned list; absent, the result is unchanged (full back-compat)."""
    result = await run_in_threadpool(get_resolver().resolve_by_binding, alg, value)
    return _cap_matches(result, max_results)


# --- Federation: forward a soft-binding query to peer resolvers on a local miss ----------------
_MAX_PEERS = 5


def _peer_is_safe(url: str) -> bool:
    """A configured peer is usable only if it is a well-formed http(s) URL, and in production only
    if it is https and not a private/loopback/link-local host. Peers come from VERIDEX_SBR_PEERS
    (operator-set), never from a request, so this guards an operator misconfiguration that could
    point a forward at an internal service, not an attacker-supplied URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if os.environ.get("APP_ENV") != "production":
        return True
    if parsed.scheme != "https":
        return False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return parsed.hostname.lower() != "localhost"


def _peer_urls() -> list[str]:
    """The configured, validated federation peers (at most _MAX_PEERS), read fresh so a changed
    VERIDEX_SBR_PEERS is picked up without a restart (and tests can set it per-case)."""
    raw = os.environ.get("VERIDEX_SBR_PEERS", "")
    peers = [u.strip() for u in raw.split(",") if u.strip() and _peer_is_safe(u.strip())]
    return peers[:_MAX_PEERS]


def _peer_client() -> httpx.AsyncClient:
    """The HTTP client used to reach federation peers. A seam so tests can inject a MockTransport
    without patching the global httpx (which the app's own clients also use)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))


async def _forward_to_peers(alg: str, value: str) -> SoftBindingQueryResult:
    """Forward a soft-binding query to each configured peer SBR node until one recovers the
    manifest, labeling it with the recovering peer. One bad peer never breaks the query: each error
    is caught and the next peer tried. No peer ever sees the asset, only the {alg, value}."""
    peers = _peer_urls()
    if not peers:
        return SoftBindingQueryResult(matches=[])
    async with _peer_client() as client:
        for base in peers:
            try:
                resp = await client.get(
                    f"{base.rstrip('/')}/matches/byBinding", params={"alg": alg, "value": value}
                )
                resp.raise_for_status()
                result = SoftBindingQueryResult.model_validate(resp.json())
            except (httpx.HTTPError, ValueError) as exc:  # network error or a malformed peer body
                logger.warning("federation: peer %s failed: %s", base, exc)
                continue
            if result.matches:
                for match in result.matches:
                    match.endpoint = base  # label which peer recovered it
                return result
    return SoftBindingQueryResult(matches=[])


@router.get(
    "/matches/byBinding/federated",
    response_model=SoftBindingQueryResult,
    include_in_schema=False,
)
async def matches_by_binding_federated(alg: str, value: str) -> SoftBindingQueryResult:
    """Federated SBR: resolve a soft binding locally; on a local miss, forward the {alg, value}
    query to the configured peer resolvers and return the first peer's recovered manifest, labeled
    with its endpoint. Recovery becomes an open, vendor-neutral network, not one repository."""
    local = await run_in_threadpool(get_resolver().resolve_by_binding, alg, value)
    if local.matches:
        return local
    return await _forward_to_peers(alg, value)


class FederationStatus(CamelModel):
    """The federation surface: whether peer-forwarding is enabled and which peers are configured. A
    live cross-node recovery needs a second resolver node with a complementary index; the forwarding
    mechanism itself is wired and tested here."""

    enabled: bool
    peers: list[str]
    note: str


@router.get("/demo/federation", response_model=FederationStatus, include_in_schema=False)
async def demo_federation() -> FederationStatus:
    peers = _peer_urls()
    note = (
        "On a local miss the resolver forwards the soft-binding query to these peer SBR nodes and "
        "returns the first peer's recovered manifest, labeled with its endpoint. A live cross-node "
        "hit needs a second node with a complementary index."
        if peers
        else "No peers configured. Set VERIDEX_SBR_PEERS to other SBR resolver URLs to federate "
        "recovery across an open, vendor-neutral network."
    )
    return FederationStatus(enabled=bool(peers), peers=peers, note=note)


# --- Receipt construction: reuse the EXISTING inclusion proof, never re-derive the Merkle math ---


def _self_base_url(request: Request) -> str:
    """Veridex public base URL, for the receipt repository + anchor URIs. Prefers
    VERIDEX_PUBLIC_URL (set it behind a proxy so the URIs name the public host), else
    the incoming request's base URL. No literal domain is hardcoded."""
    configured = os.environ.get("VERIDEX_PUBLIC_URL")
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def _inclusion_proof(manifest_id: str) -> InclusionProofResponse | None:
    """The inclusion proof for a manifest (the SAME proof GET /transparency/proof returns), or None
    when the manifest is not a leaf in the transparency log. signed_proof computes the proof, the
    root, and the signed checkpoint under one lock, so they describe one tree state. Synchronous:
    run in a threadpool."""
    log = get_log()
    index = log.index_for(manifest_id)
    manifest = _lookup_manifest(manifest_id)
    if index is None or manifest is None:
        return None
    size, root, proof, checkpoint, verified = log.signed_proof(
        index, _signing_key, datetime.now(UTC).isoformat()
    )
    return InclusionProofResponse(
        manifest_id=manifest_id,
        # index is the pymerkle 1-based position; the response field is 0-based to agree with
        # GET /transparency/log, so a client can cross-reference the two.
        leaf_index=index - 1,
        leaf_hash=manifest.canonical_hash(),
        tree_size=size,
        root_hash=root.hex(),
        proof=proof.serialize(),
        checkpoint=checkpoint,
        public_key_hex=_public_key_hex(),
        key_source=_key_source,
        server_verified=verified,
    )


def _receipt_parts(
    manifest_id: str, inclusion: InclusionProofResponse, base_url: str
) -> tuple[ReceiptRepository, ReceiptAnchor, bool]:
    """Map Rooted's real inclusion proof onto the receipt repository + anchor, and compute the real
    verified flag: the inclusion proof recomputes to the signed root (server_verified) AND the
    checkpoint signature verifies under the public key. anchor.proof is the exact proof payload
    GET /transparency/proof returns, with the hash alg labeled; the spec marks anchor.proof
    additionalProperties true, so a repository-specific Merkle proof is conformant."""
    base = base_url.rstrip("/")
    proof_obj: dict[str, Any] = {"alg": "sha256", **inclusion.model_dump(by_alias=True)}
    repository = ReceiptRepository(uri=base, manifest_id=manifest_id)
    anchor = ReceiptAnchor(
        uri=f"{base}/transparency/proof/{quote(manifest_id, safe='')}",
        parameters={"epoch": inclusion.checkpoint.epoch},
        proof=proof_obj,
    )
    verified = inclusion.server_verified and verify_checkpoint(
        inclusion.checkpoint, _signing_key.public_key()
    )
    return repository, anchor, verified


def _manifest_receipt(manifest_id: str, base_url: str) -> ManifestReceipt | None:
    """The c2pa.manifestReceipt for a manifest (no verification verdict), or None when it is not in
    the transparency log. Synchronous: run in a threadpool."""
    inclusion = _inclusion_proof(manifest_id)
    if inclusion is None:
        return None
    repository, anchor, _ = _receipt_parts(manifest_id, inclusion, base_url)
    return ManifestReceipt(repository=repository, anchor=anchor)


def _verified_receipt(manifest_id: str, base_url: str) -> VerifiedManifestReceipt | None:
    """The c2pa.verifiedManifestReceipt for a manifest (with the real verified verdict), or None if
    it is not in the transparency log. Synchronous: run in a threadpool."""
    inclusion = _inclusion_proof(manifest_id)
    if inclusion is None:
        return None
    repository, anchor, verified = _receipt_parts(manifest_id, inclusion, base_url)
    return VerifiedManifestReceipt(
        repository=repository, anchor=anchor, verified=verified, error=None
    )


def _proof_matches(
    supplied: dict[str, Any], inclusion: InclusionProofResponse
) -> tuple[bool, str | None]:
    """Re-run Rooted's real Merkle verification on a SUPPLIED proof and compare it to the current
    inclusion proof and signed root, rather than trusting any flag inside the supplied object. Any
    malformed or non-matching field yields (False, reason); a fully matching, valid proof yields
    (True, None)."""
    if supplied.get("leafHash") != inclusion.leaf_hash:
        return False, "proof leaf hash does not match the manifest canonical hash"
    if supplied.get("leafIndex") != inclusion.leaf_index:
        return False, "proof leaf index does not match the current leaf index"
    if supplied.get("treeSize") != inclusion.tree_size:
        return False, "proof tree size does not match the current tree size"
    if supplied.get("rootHash") != inclusion.root_hash:
        return False, "proof root hash does not match the current signed root"
    # Bind the supplied audit path to THIS leaf. resolve()==root alone is insufficient: in a
    # multi-leaf tree any valid proof resolves to the same root, so a receipt carrying leaf A's
    # fields but leaf B's audit path would otherwise verify. At a fixed leaf_index + tree_size
    # (both checked above) our inclusion proof is deterministic, so the caller's proof must equal
    # the proof we issue for that leaf.
    if supplied.get("proof") != inclusion.proof:
        return False, "supplied audit path is not the proof for the claimed leaf"
    try:
        checkpoint = MerkleCheckpoint.model_validate(supplied.get("checkpoint"))
        if not verify_checkpoint(checkpoint, _signing_key.public_key()):
            return False, "checkpoint signature does not verify under the repository public key"
        if checkpoint.root_hash != inclusion.root_hash:
            return False, "checkpoint root does not match the current signed root"
        _deserialized = MerkleProof.deserialize(supplied.get("proof"))
        _resolve_fn = getattr(_deserialized, "compute_root", None) or _deserialized.resolve
        resolved = _resolve_fn()
        if resolved != bytes.fromhex(inclusion.root_hash):
            return False, "merkle audit path does not resolve to the signed root"
    except Exception as exc:  # noqa: BLE001 - a malformed/forged proof is a verdict, never a 500
        logger.info("verifyReceipt: supplied proof did not verify: %s", exc)
        return False, "proof is malformed or does not verify"
    return True, None


def _verify_receipt_against_log(
    manifest_id: str, payload: ManifestReceiptInput
) -> VerifiedManifestReceipt:
    """Verify a submitted receipt against this repository's transparency log for manifest_id. Echoes
    the submitted repository/anchor with the honest verdict. A body missing the required receipt
    fields is a malformed body (400)."""
    repo = payload.repository
    anchor = payload.anchor
    if repo is None or anchor is None:
        raise HTTPException(status_code=400, detail="malformed manifest receipt body")
    repo_uri = repo.uri
    repo_mid = repo.manifest_id
    anchor_uri = anchor.uri
    anchor_proof = anchor.proof
    if not repo_uri or not repo_mid or not anchor_uri or anchor_proof is None:
        raise HTTPException(status_code=400, detail="malformed manifest receipt body")
    out_repo = ReceiptRepository(uri=repo_uri, manifest_id=repo_mid)
    out_anchor = ReceiptAnchor(uri=anchor_uri, parameters=anchor.parameters, proof=anchor_proof)

    verified = True
    error: str | None = None
    if repo_mid != manifest_id:
        verified = False
        error = "receipt repository manifestId does not match the requested manifest"
    elif payload.type_ != _RECEIPT_TYPE:
        verified = False
        error = "unexpected receipt @type (want org.c2pa.manifest-receipt)"
    else:
        inclusion = _inclusion_proof(manifest_id)
        if inclusion is None:
            verified = False
            error = "manifest is not in the transparency log"
        else:
            verified, error = _proof_matches(anchor_proof, inclusion)
    return VerifiedManifestReceipt(
        repository=out_repo, anchor=out_anchor, verified=verified, error=error
    )


def _demo_receipt(base_url: str) -> VerifiedManifestReceipt:
    """The verified receipt for the primary demo manifest, the first logged manifest as a fallback,
    or a labeled empty state when the log is empty. Never raises."""
    from veridex_api.demo import DEMO_MANIFEST_ID  # local import: avoid a module-load cycle

    entries, _size, _root = get_log().snapshot()
    ids = [mid for _idx, mid, _hash in entries]
    target = DEMO_MANIFEST_ID if DEMO_MANIFEST_ID in ids else (ids[0] if ids else None)
    if target is not None:
        receipt = _verified_receipt(target, base_url)
        if receipt is not None:
            return receipt
    base = base_url.rstrip("/")
    return VerifiedManifestReceipt(
        repository=ReceiptRepository(uri=base, manifest_id=""),
        anchor=ReceiptAnchor(uri=f"{base}/transparency/log", parameters={}, proof={}),
        verified=False,
        error="no manifest is available in the transparency log yet",
    )


# Registered BEFORE the catch-all GET /manifests/{manifest_id:path} so the greedy :path converter
# does not shadow these more specific routes.
@router.get(
    "/manifests/{manifest_id}/receipts",
    response_model=VerifiedManifestReceipt,
    response_model_exclude_none=True,
    operation_id="getVerifiedReceipt",
    responses={404: {"description": "manifest not in the transparency log (not ingested)"}},
)
async def get_verified_receipt(manifest_id: str, request: Request) -> VerifiedManifestReceipt:
    """A C2PA SBR 2.4 verified manifest receipt: portable, independently verifiable proof that this
    manifest was ingested into this repository, built from Rooted's real Merkle inclusion proof. 404
    when the manifest is not a leaf in the transparency log."""
    receipt = await run_in_threadpool(_verified_receipt, manifest_id, _self_base_url(request))
    if receipt is None:
        raise HTTPException(status_code=404, detail="manifest not in the transparency log")
    return receipt


@router.post(
    "/manifests/{manifest_id}/receipts",
    response_model=VerifiedManifestReceipt,
    response_model_exclude_none=True,
    operation_id="verifyReceipt",
    responses={400: {"description": "malformed manifest receipt body"}},
)
async def verify_receipt(
    manifest_id: str, payload: ManifestReceiptInput
) -> VerifiedManifestReceipt:
    """Verify a submitted c2pa.manifestReceipt against this repository transparency log for the path
    manifest. The verdict is honest: verified=false with an error when the receipt repository
    manifestId mismatches the path, the @type is wrong, the manifest is not in the log, or the
    supplied proof does not validate against the current inclusion proof and signed root. A body
    missing the required receipt fields is a malformed body (400)."""
    return await run_in_threadpool(_verify_receipt_against_log, manifest_id, payload)


@router.delete(
    # The `:path` converter matches the GET catch-all's pattern exactly. With the default
    # `[^/]+` converter this route matches ids (e.g. one containing a newline) that the GET
    # catch-all's `.*` regex cannot, and Starlette then answers GET with an undocumented 405
    # instead of falling through to 404.
    "/manifests/{manifest_id:path}",
    operation_id="deleteManifestRefused",
    status_code=405,
    responses={405: {"description": "append-only WORM registry: manifests cannot be deleted"}},
)
async def delete_manifest(manifest_id: str) -> None:
    """Refused by design. This registry is append-only and WORM-backed (Backblaze B2 Object Lock):
    every manifest is sealed into the transparency log and a signed checkpoint, so manifests are
    immutable and cannot be deleted. The greedy converter extends the refusal to every subpath
    (including /receipts). Rooted likewise does not implement the spec PUT /bindings mutation
    route. This is a deliberate, honest conformance statement, not a missing feature."""
    # RFC 9110: a 405 must carry an Allow header listing the methods the resource supports.
    allow = "GET, POST" if manifest_id.endswith("/receipts") else "GET"
    raise HTTPException(
        status_code=405,
        detail=(
            "manifests are immutable: this registry is append-only and WORM-backed by Backblaze B2 "
            "Object Lock, so a manifest cannot be deleted. Rooted also does not implement the spec "
            "PUT /bindings mutation route, by design."
        ),
        headers={"Allow": allow},
    )


@router.get(
    "/demo/receipt",
    response_model=VerifiedManifestReceipt,
    response_model_exclude_none=True,
    include_in_schema=False,
)
async def demo_receipt(request: Request) -> VerifiedManifestReceipt:
    """The verified manifest receipt for the primary demo manifest, for a UI panel. Degrades to the
    first manifest in the log when the primary is absent, and to a clear empty state when the log is
    empty, never 500."""
    return await run_in_threadpool(_demo_receipt, _self_base_url(request))


# --- Integrity clash: the embedded C2PA claim versus the recovered registry record --------------


def _integrity_clash() -> IntegrityClashResponse:
    """The staged integrity-clash demonstration, computed for real: the registry record recovered
    for the primary demo manifest (falling back to the first logged manifest that resolves), the
    staged embedded claim from the fixture, and the field-by-field verdict. A missing registry
    record or fixture degrades to a labeled empty state. Synchronous: run in a threadpool."""
    from veridex_api.demo import DEMO_MANIFEST_ID  # local import: avoid a module-load cycle

    embedded = load_staged_embedded_summary()
    manifest = _lookup_manifest(DEMO_MANIFEST_ID)
    if manifest is None:
        entries, _size, _root = get_log().snapshot()
        for _idx, mid, _hash in entries:
            manifest = _lookup_manifest(mid)
            if manifest is not None:
                break
    if manifest is None or embedded is None:
        reasons = []
        if manifest is None:
            reasons.append("no manifest is available in the registry yet")
        if embedded is None:
            reasons.append("the staged embedded-claim fixture is unavailable")
        return IntegrityClashResponse(
            staged=True,
            staged_note=STAGED_NOTE,
            available=False,
            embedded=embedded,
            note="; ".join(reasons),
        )
    disclosed = manifest.redacted()  # SB 942 split: compare and disclose the read-time view
    verdict = compare_provenance(disclosed, embedded)
    if verdict.clash:
        note = (
            f"{len(verdict.contradictions)} contradiction(s) between the embedded claim and the "
            "recovered registry record: the embedded provenance is laundered or forged."
        )
    else:
        note = (
            "the embedded claim agrees with the recovered registry record on every compared field"
        )
    return IntegrityClashResponse(
        staged=True,
        staged_note=STAGED_NOTE,
        available=True,
        manifest_id=manifest.manifest_id,
        recovered=disclosed,
        embedded=embedded,
        verdict=verdict,
        note=note,
    )


@router.get(
    "/demo/integrity-clash",
    response_model=IntegrityClashResponse,
    include_in_schema=False,
)
async def demo_integrity_clash() -> IntegrityClashResponse:
    """Integrity-clash detection, demonstrated on a STAGED forged claim (labeled in the response):
    the embedded manifest summary claims a human camera capture while the registry record recovered
    for the asset proves AI generation by a named model. Rooted holds both provenance layers, so it
    names the contradiction field by field. The verdict is computed, never hardcoded; a missing
    registry record or fixture returns a labeled empty state, never a 500."""
    return await run_in_threadpool(_integrity_clash)


@router.get(
    "/manifests/{manifest_id:path}",
    response_model=Manifest,
    responses={404: {"description": "manifest not found"}},
)
async def get_manifest(manifest_id: str) -> Manifest:
    manifest = await run_in_threadpool(_lookup_manifest, manifest_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="manifest not found")
    return manifest.redacted()  # SB 942 split: withhold personal provenance on read


class VerifyRequest(CamelModel):
    """A manifest plus a COSE_Sign1 signature (base64) to check against the checkpoint key."""

    manifest: Manifest
    signature_b64: str


class VerifyResponse(CamelModel):
    """Whether the signature covers this exact manifest, with the key it was checked against."""

    signature_valid: bool
    public_key_hex: str
    key_source: str


@router.post("/verify", response_model=VerifyResponse)
async def verify(req: VerifyRequest) -> VerifyResponse:
    """Verify a manifest against a COSE signature using the server's checkpoint public key. Changing
    ANY signed field (manifest id, asset hash, created-at, system provenance) makes this False, so a
    client can prove tamper-evidence live. Adversarial input (bad base64, malformed COSE, a tampered
    manifest) collapses to signatureValid=false, never a 500."""
    try:
        cose = base64.b64decode(req.signature_b64, validate=True)
    except (binascii.Error, ValueError):
        valid = False
    else:
        valid = await run_in_threadpool(
            verify_manifest, cose, req.manifest, _signing_key.public_key()
        )
    return VerifyResponse(
        signature_valid=valid, public_key_hex=_public_key_hex(), key_source=_key_source
    )


class CheckpointResponse(CamelModel):
    """A signed Merkle tree head plus the public key to verify it independently.

    key_source is "configured" for a real loaded key or "ephemeral" for a dev/CI key, so a client
    never mistakes a throwaway key for a trust anchor.
    """

    checkpoint: MerkleCheckpoint
    public_key_hex: str
    key_source: str


class InclusionProofResponse(CamelModel):
    """A self-contained, independently-verifiable inclusion proof.

    The client resolves the serialized proof to a root and confirms that root equals the embedded
    signed checkpoint's root_hash, then verifies the checkpoint signature against public_key_hex.
    server_verified is only the server's own check and is not a substitute for that client-side
    verification. leaf_hash is the canonical hash of the signed manifest. Newly signed manifests
    keep personal provenance (e.g. the generation prompt) out of the canonical payload, so their
    redacted disclosure from GET /manifests hashes identically to this leaf. A legacy leaf whose
    personal data was signed into system_provenance keeps its original hash (the log is append-only
    and WORM-anchored), so its redacted disclosure differs by design.
    """

    manifest_id: str
    leaf_index: int
    leaf_hash: str
    tree_size: int
    root_hash: str
    proof: dict[str, Any]
    checkpoint: MerkleCheckpoint
    public_key_hex: str
    key_source: str
    server_verified: bool


class ConsistencyProofResponse(CamelModel):
    """A self-contained, independently-verifiable Merkle consistency proof: the current log is an
    append-only extension of the tree at prior_size (no earlier leaf altered or removed). The client
    resolves the serialized proof from prior_root_hash to root_hash and confirms it, then binds
    root_hash to the embedded signed checkpoint. server_verified is only this server's own check.
    This is the same append-only guarantee Certificate Transparency publishes."""

    prior_size: int
    prior_root_hash: str
    tree_size: int
    root_hash: str
    proof: dict[str, Any]
    checkpoint: MerkleCheckpoint
    public_key_hex: str
    key_source: str
    server_verified: bool


class LogEntry(CamelModel):
    """One append-ordered transparency-log leaf."""

    leaf_index: int
    manifest_id: str
    leaf_hash: str


class LogResponse(CamelModel):
    """The ordered transparency-log leaves with the current tree head, for auditing and display."""

    entries: list[LogEntry]
    tree_size: int
    root_hash: str


@router.get("/transparency/log", response_model=LogResponse)
async def transparency_log() -> LogResponse:
    """The append-ordered log leaves plus the current root. A transparency log is meant to be
    auditable, so the entries are public; this also feeds the Merkle explorer."""
    # One snapshot: entries, size, and root read in a single synchronous pass in the threadpool,
    # so the leaf list, the tree size, and the root cannot disagree under a concurrent append.
    rows, size, root = await run_in_threadpool(get_log().snapshot)
    return LogResponse(
        entries=[LogEntry(leaf_index=i, manifest_id=m, leaf_hash=h) for i, m, h in rows],
        tree_size=size,
        root_hash=root.hex(),
    )


@router.get("/transparency/checkpoint", response_model=CheckpointResponse)
async def transparency_checkpoint() -> CheckpointResponse:
    """The current signed tree head. Idempotent: the epoch is the tree size, so re-reading an
    unchanged tree returns the same signed checkpoint. The public key travels with it."""
    return CheckpointResponse(
        checkpoint=_signed_head(), public_key_hex=_public_key_hex(), key_source=_key_source
    )


@router.get(
    "/transparency/proof/{manifest_id:path}",
    response_model=InclusionProofResponse,
    responses={404: {"description": "manifest not in transparency log"}},
)
async def transparency_proof(manifest_id: str) -> InclusionProofResponse:
    """An inclusion proof for a manifest, pinned to a signed checkpoint so the client can bind the
    leaf to a signed tree head without trusting this endpoint. _inclusion_proof is the same builder
    the receipt routes reuse, so a receipt anchor.proof is exactly this payload. It runs off the
    event loop (CPU-bound proof + a blocking index read)."""
    proof = await run_in_threadpool(_inclusion_proof, manifest_id)
    if proof is None:
        raise HTTPException(status_code=404, detail="manifest not in transparency log")
    return proof


@router.get(
    "/transparency/consistency/{prior_size}",
    response_model=ConsistencyProofResponse,
    responses={404: {"description": "no such prior tree size (must be 1..current tree size)"}},
)
async def transparency_consistency(prior_size: int) -> ConsistencyProofResponse:
    """A Certificate-Transparency-style consistency proof that the log only appended (never altered
    or removed a leaf) between an earlier published tree size and the current head, pinned to the
    signed current checkpoint. This is the append-only guarantee that makes the ledger auditable."""
    # signed_consistency computes the two roots, the proof, and the signed checkpoint under one lock
    # (a consistent snapshot) off the event loop. A prior_size outside 1..current is a state that
    # never existed in the log, so 404 (not 400): that historical tree size is simply not there.
    try:
        psize, proot, size, root, proof, checkpoint, verified = await run_in_threadpool(
            get_log().signed_consistency, prior_size, _signing_key, datetime.now(UTC).isoformat()
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ConsistencyProofResponse(
        prior_size=psize,
        prior_root_hash=proot.hex(),
        tree_size=size,
        root_hash=root.hex(),
        proof=proof.serialize(),
        checkpoint=checkpoint,
        public_key_hex=_public_key_hex(),
        key_source=_key_source,
        server_verified=verified,
    )
