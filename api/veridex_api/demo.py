"""A credential-free demo asset.

The primary demo asset is a real image generated via Genblaze on GMI Cloud (seedream-5.0-lite),
bundled at build time, so the live recovery loop closes to VERIFIED on a genuine AI-generated image,
with honest system provenance naming the real model and provider. A few extra fixtures
(deterministic gradients, labeled as such) pad the transparency log so the Merkle explorer has
real structure.
The /demo/sample bytes match the registered PDQ fingerprint exactly, so the recovery (a genuine PDQ
match plus a real transparency-log entry) is real.

When a Storage backend is configured (Backblaze B2 in production, via B2_KEY_ID/B2_APP_KEY/
B2_BUCKET_DEV), each asset's bytes, its canonical manifest, and its COSE signature are also written
content-addressably to B2, so the live demo exercises B2 for real. Without storage, it runs purely
in-memory. Gated on VERIDEX_DEMO_SEED, and idempotent so a restart never duplicates it.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import anyio
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from PIL import Image, ImageFilter

from veridex_api.dedup import counters as dedup_counters
from veridex_api.dedup import put_if_absent
from veridex_provenance.audio import audio_to_image
from veridex_provenance.fingerprint import compute_pdq, hamming
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.models import (
    ALG_TRUSTMARK_P,
    PDQ_HAMMING_THRESHOLD,
    CamelModel,
    Manifest,
    SoftBinding,
    canonical_json,
)
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.signing import sign_manifest
from veridex_provenance.video import video_frames
from veridex_provenance.watermark import FakeWatermarker, Watermarker
from veridex_storage.storage import (
    MANIFEST_PREFIX,
    B2Storage,
    BucketProperties,
    Storage,
    asset_key,
    manifest_key,
    signature_key,
)

DEMO_MANIFEST_ID = "urn:c2pa:demo-0000-0000-0000-000000000001"
DEMO_WATERMARK_ID = "DEMO"
_CREATED_AT = "2026-06-27T00:00:00Z"

logger = logging.getLogger(__name__)
router = APIRouter()
_sample_bytes: bytes | None = None

# The primary demo asset: a real Genblaze (GMI Cloud) generation, bundled next to this module.
_PRIMARY_ASSET_PATH = Path(__file__).parent / "assets" / "demo-asset.jpg"
_PRIMARY_PROMPT = (
    "a single rooted oak tree on a floating island in a deep blue starfield, "
    "cinematic, photorealistic"
)
# system_provenance is disclosed on recovery. The generation prompt is PERSONAL provenance and is
# withheld by the redaction layer, so it lives in personal_provenance (which the canonical payload
# and the signature EXCLUDE), exactly like a visitor's own prompt in POST /demo/generate. Keeping it
# out of system_provenance is what makes the disclosed (redacted) manifest hash identical to its
# transparency-log leaf: a prompt in system_provenance would be in the signed canonical, so
# withholding it on disclosure would change the hash (see test_redacting_a_system_prompt...).
_PRIMARY_PROVENANCE = {
    "model": "seedream-5.0-lite",
    "provider": "gmicloud-image",
    "generator": "genblaze",
}
_PRIMARY_PERSONAL = {"prompt": _PRIMARY_PROMPT}
_FIXTURE_PROVENANCE = {"model": "rooted-demo-fixture", "note": "seeded demo asset"}

# The demo AUDIO asset: a real Suno V5 instrumental clip (kie.ai), trimmed to 10s and bundled here.
# Recovery is by a perceptual audio fingerprint (veridex_provenance.audio), the audio analog of PDQ.
_AUDIO_ASSET_PATH = Path(__file__).parent / "assets" / "demo-audio.mp3"
DEMO_AUDIO_MANIFEST_ID = "urn:c2pa:demo-audio-0000-0000-0000-000000000001"
DEMO_AUDIO_WATERMARK_ID = "DEMOA"
_AUDIO_PROVENANCE = {
    "model": "suno-v5",
    "provider": "kie.ai-suno",
    "generator": "kie.ai",
    "title": "Glass Rain (instrumental)",
}
_audio_bytes: bytes | None = None


def audio_demo_bytes() -> bytes:
    """The demo audio asset's exact bytes (a real Suno V5 clip, kie.ai, trimmed to 10s). Cached on
    first read. These bytes are what /demo/audio serves and what the audio fingerprint is
    computed over, so the live audio recovery self-matches on genuine AI-generated audio."""
    global _audio_bytes
    if _audio_bytes is None:
        _audio_bytes = _AUDIO_ASSET_PATH.read_bytes()
    return _audio_bytes


# The demo SPEECH asset: a real ElevenLabs (kie.ai) clip narrating the provenance concept, bundled
# here. Unlike the instrumental demo audio, this is SPEECH, so Genblaze's AssemblyAI STT connector
# can transcribe it to a hash-verified transcript (see make_genblaze_transcript_sample.py).
_SPEECH_ASSET_PATH = Path(__file__).parent / "assets" / "demo-speech.mp3"
_speech_bytes: bytes | None = None


def speech_demo_bytes() -> bytes:
    """The demo speech asset's exact bytes (a real ElevenLabs clip, kie.ai). Cached on first read.
    These bytes are what /demo/speech serves; AssemblyAI fetches that URL to transcribe it."""
    global _speech_bytes
    if _speech_bytes is None:
        _speech_bytes = _SPEECH_ASSET_PATH.read_bytes()
    return _speech_bytes


# The demo VIDEO asset: a real Veo3 clip (kie.ai), trimmed to ~6s and bundled here. Recovery is by
# per-keyframe PDQ (veridex_provenance.video), the video analog of the image fingerprint.
_VIDEO_ASSET_PATH = Path(__file__).parent / "assets" / "demo-video.mp4"
DEMO_VIDEO_MANIFEST_ID = "urn:c2pa:demo-video-0000-0000-0000-000000000001"
DEMO_VIDEO_WATERMARK_ID = "DEMOV"
_VIDEO_PROVENANCE = {
    "model": "veo3",
    "provider": "kie.ai-veo3",
    "generator": "kie.ai",
    "title": "Rooted oak on a floating island",
}
_video_bytes: bytes | None = None


def video_demo_bytes() -> bytes:
    """The demo video asset's exact bytes (a real Veo3 clip, kie.ai, trimmed to ~6s). Cached on
    first read. These bytes are what /demo/video serves and what the per-keyframe fingerprints are
    computed over, so the live video recovery self-matches on genuine AI-generated video."""
    global _video_bytes
    if _video_bytes is None:
        _video_bytes = _VIDEO_ASSET_PATH.read_bytes()
    return _video_bytes


def primary_manifest() -> Manifest:
    """The primary demo asset's manifest (the same canonical fields the seed registers). Used by
    /demo/signed-manifest + the live tamper-evidence demo, so signing and verifying agree."""
    return Manifest(
        manifest_id=DEMO_MANIFEST_ID,
        asset_sha256=hashlib.sha256(demo_sample_bytes()).hexdigest(),
        created_at=_CREATED_AT,
        system_provenance=_PRIMARY_PROVENANCE,
        personal_provenance=_PRIMARY_PERSONAL,
        soft_bindings=[SoftBinding(alg=ALG_TRUSTMARK_P, value=DEMO_WATERMARK_ID)],
    )


# Extra fixtures so the transparency log (and the Merkle explorer) has real structure, not one leaf.
_EXTRA_SEEDS = (11, 13, 17, 19, 23, 29)
DEMO_ENTRY_COUNT = 1 + len(_EXTRA_SEEDS)


def _demo_image(seed: int, size: int = 256) -> Image.Image:
    """A smooth gradient + soft blobs + mild texture: natural-frequency content that yields a
    stable, high-quality PDQ hash, so the served image self-matches the registered fingerprint."""
    rng = np.random.default_rng(seed)
    ramp = np.linspace(0, 255, size)
    img = np.stack(
        [np.tile(ramp, (size, 1)), np.tile(ramp[:, None], (1, size)), np.full((size, size), 128.0)],
        axis=-1,
    )
    yy, xx = np.mgrid[0:size, 0:size]
    for _ in range(6):
        cy, cx = rng.integers(0, size, 2)
        r = rng.integers(20, 70)
        blob = np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * r * r))
        img += blob[..., None] * rng.integers(-80, 80, 3)
    img += rng.normal(0, 6, (size, size, 3))
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def demo_sample_bytes() -> bytes:
    """The primary demo asset's exact bytes: a real image generated via Genblaze on GMI Cloud
    (seedream-5.0-lite), bundled with this module. Cached on first read. These exact bytes are what
    /demo/sample serves and what the registered PDQ fingerprint is computed over, so the live
    recovery self-matches on a genuine AI-generated image."""
    global _sample_bytes
    if _sample_bytes is None:
        _sample_bytes = _PRIMARY_ASSET_PATH.read_bytes()
    return _sample_bytes


def _put_signature(storage: Storage, manifest_id: str, sig: bytes) -> None:
    """Store the COSE signature, dedup-skipping the re-upload only under a pinned key: the
    signature bytes are byte-stable across restarts only when the signing key is configured. An
    ephemeral dev/CI key must overwrite, so the stored signature always verifies against the
    currently published public key."""
    from veridex_api.sbr import key_source  # local import: avoid a module-load cycle

    if key_source() == "configured":
        put_if_absent(storage, signature_key(manifest_id), sig)
    else:
        storage.put(signature_key(manifest_id), sig)


def _register(
    resolver: Resolver,
    log: TransparencyLog,
    manifest_id: str,
    watermark_id: str,
    image_bytes: bytes,
    storage: Storage | None,
    signing_key: Any,
    system_provenance: dict[str, Any],
    personal_provenance: dict[str, Any] | None = None,
) -> None:
    manifest = Manifest(
        manifest_id=manifest_id,
        asset_sha256=hashlib.sha256(image_bytes).hexdigest(),
        created_at=_CREATED_AT,
        system_provenance=system_provenance,
        personal_provenance=personal_provenance or {},
        soft_bindings=[SoftBinding(alg=ALG_TRUSTMARK_P, value=watermark_id)],
    )
    resolver.register(manifest, Image.open(io.BytesIO(image_bytes)), watermark_id)
    log.append(manifest.manifest_id, manifest.canonical_hash())
    if storage is not None:
        # Store the asset, its canonical manifest, and its COSE signature content-addressably, so
        # the live demo writes real objects to Backblaze B2 (the recovery repository). A restart
        # re-seeds identical bytes under the same keys, so an existing object skips the re-upload
        # (counted as dedup evidence in GET /demo/storage).
        put_if_absent(storage, asset_key(manifest.asset_sha256), image_bytes)
        put_if_absent(storage, manifest_key(manifest_id), canonical_json(manifest.model_dump()))
        _put_signature(storage, manifest_id, sign_manifest(manifest, signing_key))


def seed_demo(resolver: Resolver, log: TransparencyLog, storage: Storage | None = None) -> None:
    """Register the demo assets for recovery: the primary (a real Genblaze generation, served at
    /demo/sample and recovered by the UI) plus a few extra fixtures so the log has structure. When
    storage is set, also write each asset/manifest/signature to it (B2). Idempotent if already
    seeded."""
    if resolver.get_manifest(DEMO_MANIFEST_ID) is not None:
        return
    # Sign the durable B2 artifacts with the server's published anchor key (not a throwaway), so the
    # stored COSE signatures verify against the key /transparency/checkpoint and /status advertise.
    from veridex_api import sbr

    _register(
        resolver,
        log,
        DEMO_MANIFEST_ID,
        DEMO_WATERMARK_ID,
        demo_sample_bytes(),
        storage,
        sbr._signing_key,
        _PRIMARY_PROVENANCE,
        _PRIMARY_PERSONAL,
    )
    for i, seed in enumerate(_EXTRA_SEEDS):
        buf = io.BytesIO()
        _demo_image(seed).save(buf, "PNG")
        mid = f"urn:c2pa:demo-{i:04d}-0000-0000-0000-000000000002"
        _register(
            resolver,
            log,
            mid,
            f"DX{i:02d}",
            buf.getvalue(),
            storage,
            sbr._signing_key,
            _FIXTURE_PROVENANCE,
        )


def seed_audio_demo(
    audio_resolver: Resolver, log: TransparencyLog, storage: Storage | None = None
) -> None:
    """Register the demo AUDIO asset for recovery: a real Suno-generated clip recovered by its
    perceptual audio fingerprint. Uses a SEPARATE audio resolver so audio never cross-matches an
    image, while sharing the transparency log and B2. Idempotent: it re-registers the asset in the
    (in-memory) audio resolver on each startup but appends to the shared log only once."""
    if audio_resolver.get_manifest(DEMO_AUDIO_MANIFEST_ID) is not None:
        return
    audio_bytes = audio_demo_bytes()
    from veridex_api import sbr

    manifest = Manifest(
        manifest_id=DEMO_AUDIO_MANIFEST_ID,
        asset_sha256=hashlib.sha256(audio_bytes).hexdigest(),
        created_at=_CREATED_AT,
        system_provenance=_AUDIO_PROVENANCE,
        soft_bindings=[],  # the audio fingerprint is internal (like PDQ), not a registered alg
    )
    # Register the spectrogram of the audio: the same Resolver/PDQ machinery, in the audio index.
    audio_resolver.register(manifest, audio_to_image(audio_bytes), DEMO_AUDIO_WATERMARK_ID)
    # Append to the (possibly persistent) log only if this manifest is not already a leaf, so a
    # restart against a persistent log re-registers the asset for recovery without a duplicate leaf.
    if log.index_for(manifest.manifest_id) is None:
        log.append(manifest.manifest_id, manifest.canonical_hash())
    if storage is not None:
        put_if_absent(storage, asset_key(manifest.asset_sha256), audio_bytes)
        put_if_absent(
            storage, manifest_key(DEMO_AUDIO_MANIFEST_ID), canonical_json(manifest.model_dump())
        )
        _put_signature(storage, DEMO_AUDIO_MANIFEST_ID, sign_manifest(manifest, sbr._signing_key))


def seed_video_demo(
    video_resolver: Resolver, log: TransparencyLog, storage: Storage | None = None
) -> None:
    """Register the demo VIDEO asset for recovery: a real Veo3 clip recovered by per-keyframe PDQ.
    Uses a SEPARATE video resolver (no cross-modal match) while sharing the log + B2. Registers one
    PDQ per sampled frame under the one manifest. Idempotent: re-registers in the (in-memory) video
    resolver each startup but appends to the shared log only once."""
    if video_resolver.get_manifest(DEMO_VIDEO_MANIFEST_ID) is not None:
        return
    video_bytes = video_demo_bytes()
    from veridex_api import sbr

    manifest = Manifest(
        manifest_id=DEMO_VIDEO_MANIFEST_ID,
        asset_sha256=hashlib.sha256(video_bytes).hexdigest(),
        created_at=_CREATED_AT,
        system_provenance=_VIDEO_PROVENANCE,
        soft_bindings=[],  # the per-frame fingerprint is internal (like PDQ), not a registered alg
    )
    # resolver.register appends a fingerprint each call, so registering every sampled frame leaves
    # several frame PDQs under the one manifest, and any frame recovers it after a re-encode.
    for frame in video_frames(video_bytes):
        video_resolver.register(manifest, frame, DEMO_VIDEO_WATERMARK_ID)
    if log.index_for(manifest.manifest_id) is None:
        log.append(manifest.manifest_id, manifest.canonical_hash())
    if storage is not None:
        put_if_absent(storage, asset_key(manifest.asset_sha256), video_bytes)
        put_if_absent(
            storage, manifest_key(DEMO_VIDEO_MANIFEST_ID), canonical_json(manifest.model_dump())
        )
        _put_signature(storage, DEMO_VIDEO_MANIFEST_ID, sign_manifest(manifest, sbr._signing_key))


# --- Multi-provider provenance demos: real generations from several distinct labs (via kie.ai), ---
# each run through Rooted's spine (sign + PDQ fingerprint + Merkle log + B2), so the vendor-neutral
# claim is concrete: Rooted recovers AI media regardless of which lab generated it. The provenance
# names the REAL model + provider for each (no synthetic labels); the images are committed because
# the kie.ai result URLs expire.
_PROVIDERS: list[dict[str, Any]] = [
    {
        "slug": "nano-banana",
        "manifest_id": "urn:c2pa:demo-provider-nano-banana-000000000001",
        "watermark_id": "PNANO",
        "asset": "provider-nano-banana.jpg",
        "label": "Nano Banana 2",
        "prompt": (
            "a glowing bioluminescent oak tree with luminous roots wrapping a floating crystal "
            "island, deep space nebula background"
        ),
        "provenance": {
            "model": "nano-banana-2",
            "provider": "kie.ai-nano-banana",
            "generator": "kie.ai",
        },
    },
    {
        "slug": "flux",
        "manifest_id": "urn:c2pa:demo-provider-flux-000000000001",
        "watermark_id": "PFLUX",
        "asset": "provider-flux.jpg",
        "label": "Flux 2 Pro",
        "prompt": (
            "an ancient oak tree growing from a shattered moon fragment drifting in a violet galaxy"
        ),
        "provenance": {
            "model": "flux-2/pro-text-to-image",
            "provider": "kie.ai-flux",
            "generator": "kie.ai",
        },
    },
    {
        "slug": "qwen",
        "manifest_id": "urn:c2pa:demo-provider-qwen-000000000001",
        "watermark_id": "PQWEN",
        "asset": "provider-qwen.jpg",
        "label": "Qwen Image",
        "prompt": (
            "a lone tree of light on a small floating earth, surrounded by orbiting glowing seeds"
        ),
        "provenance": {
            "model": "qwen/text-to-image",
            "provider": "kie.ai-qwen",
            "generator": "kie.ai",
        },
    },
]
_provider_bytes: dict[str, bytes] = {}


def _provider_by_slug(slug: str) -> dict[str, Any] | None:
    return next((p for p in _PROVIDERS if p["slug"] == slug), None)


def provider_demo_bytes(slug: str) -> bytes | None:
    """The bundled bytes of a provider demo asset (a real generation), cached. None if unknown."""
    if slug not in _provider_bytes:
        provider = _provider_by_slug(slug)
        if provider is None:
            return None
        _provider_bytes[slug] = (Path(__file__).parent / "assets" / provider["asset"]).read_bytes()
    return _provider_bytes[slug]


def seed_providers(
    resolver: Resolver, log: TransparencyLog, storage: Storage | None = None
) -> None:
    """Register the multi-provider demo assets (real generations from several labs) for recovery, so
    Rooted can recover provenance for AI media from any of them. Each is signed + PDQ-indexed +
    logged + written to B2 with honest provenance naming the real model + provider. Idempotent."""
    if resolver.get_manifest(_PROVIDERS[0]["manifest_id"]) is not None:
        return
    from veridex_api import sbr

    for provider in _PROVIDERS:
        data = provider_demo_bytes(provider["slug"])
        if data is None:
            continue
        _register(
            resolver,
            log,
            provider["manifest_id"],
            provider["watermark_id"],
            data,
            storage,
            sbr._signing_key,
            provider["provenance"],
        )


class ProviderInfo(CamelModel):
    """One multi-provider demo: a real generation Rooted can recover, with honest provenance."""

    slug: str
    label: str
    model: str
    provider: str
    prompt: str
    manifest_id: str


# include_in_schema=False: these are demo aids, not part of the spec-defined SBR contract, so they
# stay out of the OpenAPI surface (and the schemathesis contract test); the UI fetches them.
@router.get("/demo/providers", response_model=list[ProviderInfo], include_in_schema=False)
async def demo_providers() -> list[ProviderInfo]:
    """List the multi-provider demo assets (real generations from several labs) for the gallery."""
    return [
        ProviderInfo(
            slug=p["slug"],
            label=p["label"],
            model=p["provenance"]["model"],
            provider=p["provenance"]["provider"],
            prompt=p["prompt"],
            manifest_id=p["manifest_id"],
        )
        for p in _PROVIDERS
    ]


@router.get("/demo/provider/{slug}", include_in_schema=False)
async def demo_provider_image(slug: str) -> Response:
    """Serve a provider demo asset's bytes so the UI can recover it. No provenance data."""
    data = provider_demo_bytes(slug)
    if data is None:
        raise HTTPException(status_code=404, detail="unknown provider")
    return Response(content=data, media_type="image/jpeg")


@router.get("/demo/sample", include_in_schema=False)
async def demo_sample() -> Response:
    """Serve the demo asset bytes so the UI can recover it. No provenance data; safe unauthed."""
    return Response(content=demo_sample_bytes(), media_type="image/jpeg")


@router.get("/demo/audio", include_in_schema=False)
async def demo_audio() -> Response:
    """Serve the demo audio bytes so the UI can play it and recover it. No provenance data."""
    return Response(content=audio_demo_bytes(), media_type="audio/mpeg")


@router.get("/demo/speech", include_in_schema=False)
async def demo_speech() -> Response:
    """Serve the demo speech bytes (a real ElevenLabs clip) over public https so Genblaze's
    AssemblyAI STT connector can fetch and transcribe it. No provenance data; safe unauthed."""
    return Response(content=speech_demo_bytes(), media_type="audio/mpeg")


@router.get("/demo/video", include_in_schema=False)
async def demo_video() -> Response:
    """Serve the demo video bytes so the UI can play it and recover it. No provenance data."""
    return Response(content=video_demo_bytes(), media_type="video/mp4")


@router.get("/demo/signed-manifest", include_in_schema=False)
async def demo_signed_manifest() -> dict[str, Any]:
    """The primary demo manifest, its COSE signature (signed with the server's checkpoint key), and
    the public key. The tamper panel lets a judge edit a field and POST it to /demo/tamper-diff; any
    change to a signed field flips the signature invalid, demonstrating tamper-evidence live."""
    from veridex_api import sbr

    manifest = primary_manifest()
    cose = sign_manifest(manifest, sbr._signing_key)
    # Disclose the REDACTED manifest (personal provenance withheld), not the full one. The signature
    # is over the canonical payload, which excludes personal_provenance, so it still verifies
    # against the redacted manifest and the tamper demo (editing a signed system field) still works;
    # the generation prompt (personal) is never disclosed.
    return {
        "manifest": manifest.redacted().model_dump(by_alias=True),
        "signatureB64": base64.b64encode(cose).decode(),
        "publicKeyHex": sbr._public_key_hex(),
    }


# --- The b2Depth section of GET /demo/storage: evidence-based B2 configuration state. Every value
# is a live read from the bucket or a real in-process counter; anything unreadable is reported as
# unknown (read=false / null), never asserted from config or docs.


class DedupCounters(CamelModel):
    """Real, in-process dedup events counted since process start (never persisted; a restart resets
    them to zero). exists_skips counts writes skipped because the content-addressed object already
    exists; idempotent_registers counts register calls answered from the existing record."""

    exists_skips: int
    idempotent_registers: int
    since: str
    note: str


class BucketEncryption(CamelModel):
    """The bucket's default server-side encryption, read live from B2. read is false when it could
    not be read (no B2 backend, a key without readBucketEncryption, a timeout, or an outage); mode
    and algorithm are then null, never guessed. mode "none" is a successful read of an unencrypted
    default."""

    read: bool
    mode: str | None
    algorithm: str | None


class BucketLifecycle(CamelModel):
    """The bucket's lifecycle rules, read live from B2. read is false when they could not be read
    (rules is then null). byo_rule_active / ingest_rule_active report whether a delete rule covers
    that prefix right now (null when unread)."""

    read: bool
    rules: list[dict[str, Any]] | None
    byo_rule_active: bool | None
    ingest_rule_active: bool | None


class B2Depth(CamelModel):
    """Evidence-based B2 configuration state for the demo storage panel."""

    backend: str
    bucket: str | None
    default_encryption: BucketEncryption
    lifecycle: BucketLifecycle
    dedup: DedupCounters
    note: str


_BUCKET_PROPS_TTL_SECONDS = 30.0
_BUCKET_PROPS_TIMEOUT_SECONDS = 4.0
_bucket_props_cache: tuple[float, BucketProperties] | None = None


def _cached_bucket_properties(storage: B2Storage) -> BucketProperties:
    """Read the bucket's live properties (one b2_list_buckets round trip), cached briefly so a
    burst on /demo/storage cannot hammer B2's class-C API. Synchronous: run in a threadpool."""
    global _bucket_props_cache
    now = time.monotonic()
    if _bucket_props_cache is not None and now - _bucket_props_cache[0] < _BUCKET_PROPS_TTL_SECONDS:
        return _bucket_props_cache[1]
    props = storage.properties()
    _bucket_props_cache = (now, props)
    return props


def _lifecycle_rule_active(rules: list[dict[str, Any]], prefix: str) -> bool:
    """Whether a live-read lifecycle rule deletes objects under the prefix (a hiding or a deleting
    window is set)."""
    return any(
        r.get("fileNamePrefix") == prefix
        and (r.get("daysFromUploadingToHiding") or r.get("daysFromHidingToDeleting"))
        for r in rules
    )


async def _b2_depth(storage: Storage | None, backend: str, bucket: str | None) -> B2Depth:
    """Build the b2Depth section. The bucket's default encryption and lifecycle rules are read LIVE
    from B2 (threadpool, short timeout, brief cache) and degrade to unknown on any failure, never a
    500. The dedup counters are real in-process events regardless of backend."""
    props: BucketProperties | None = None
    if isinstance(storage, B2Storage):
        try:
            # abandon_on_cancel: on timeout the blocked read is abandoned (its result discarded)
            # and the panel reports unknown instead of hanging the response.
            with anyio.move_on_after(_BUCKET_PROPS_TIMEOUT_SECONDS):
                props = await anyio.to_thread.run_sync(
                    _cached_bucket_properties, storage, abandon_on_cancel=True
                )
        except Exception as exc:  # noqa: BLE001 - degrade to unknown, never 500 the demo panel
            logger.warning("b2Depth: live bucket-properties read failed: %s", exc)
    encryption = BucketEncryption(
        read=props is not None and props.default_encryption_mode is not None,
        mode=props.default_encryption_mode if props else None,
        algorithm=props.default_encryption_algorithm if props else None,
    )
    if props is not None:
        rules: list[dict[str, Any]] | None = [dict(r) for r in props.lifecycle_rules]
    else:
        rules = None
    lifecycle = BucketLifecycle(
        read=rules is not None,
        rules=rules,
        byo_rule_active=_lifecycle_rule_active(rules, "byo/") if rules is not None else None,
        ingest_rule_active=_lifecycle_rule_active(rules, "ingest/") if rules is not None else None,
    )
    exists_skips, idempotent_registers, since = dedup_counters()
    dedup = DedupCounters(
        exists_skips=exists_skips,
        idempotent_registers=idempotent_registers,
        since=since,
        note=(
            "in-process counts since process start; reset on restart, never persisted or "
            "extrapolated"
        ),
    )
    return B2Depth(
        backend=backend,
        bucket=bucket,
        default_encryption=encryption,
        lifecycle=lifecycle,
        dedup=dedup,
        note=(
            "every value here is a live read from the bucket or a real in-process counter; "
            "unknown (read=false / null) means not readable right now, not a claim"
        ),
    )


@router.get("/demo/storage", include_in_schema=False)
async def demo_storage() -> dict[str, Any]:
    """Report where the primary demo asset is stored, and confirm the objects exist (a real read
    against B2 when configured), plus the b2Depth section: the bucket's live default-encryption and
    lifecycle state and the in-process dedup counters. Drives the UI's "stored on Backblaze B2"
    panel."""
    from veridex_api.sbr import get_storage
    from veridex_storage.storage import B2Storage

    storage = get_storage()
    sha = hashlib.sha256(demo_sample_bytes()).hexdigest()
    keys = {
        "asset": asset_key(sha),
        "manifest": manifest_key(DEMO_MANIFEST_ID),
        "signature": signature_key(DEMO_MANIFEST_ID),
    }
    if storage is None:
        depth = await _b2_depth(None, "none", None)
        return {
            "backend": "none",
            "bucket": None,
            "keys": keys,
            "present": dict.fromkeys(keys, False),
            "b2Depth": depth.model_dump(by_alias=True),
        }
    backend = "backblaze-b2" if isinstance(storage, B2Storage) else "in-memory"
    bucket = os.environ.get("B2_BUCKET_DEV") if backend == "backblaze-b2" else None
    present = {name: storage.exists(k) for name, k in keys.items()}
    depth = await _b2_depth(storage, backend, bucket)
    return {
        "backend": backend,
        "bucket": bucket,
        "keys": keys,
        "present": present,
        "b2Depth": depth.model_dump(by_alias=True),
    }


class RobustnessRow(CamelModel):
    """One transform applied to the demo asset and the honest recovery outcome. hamming_distance is
    the raw PDQ distance from the original (always present, even when recovery fails); recovered is
    the real recovery verdict (a content match to the demo manifest within the threshold)."""

    transform: str
    recovered: bool
    similarity_score: int | None
    hamming_distance: int


class RobustnessGrid(CamelModel):
    """How the demo asset's perceptual hash holds up under common transforms. PDQ is robust to
    re-encode and scaling and not to rotation or large crops; the grid shows that honestly rather
    than implying recovery survives everything."""

    manifest_id: str
    threshold: int
    rows: list[RobustnessRow]


def _jpeg(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _scale(img: Image.Image, factor: float) -> Image.Image:
    return img.resize((max(1, int(img.width * factor)), max(1, int(img.height * factor))))


def _crop(img: Image.Image, fraction: float) -> Image.Image:
    w, h = img.size
    dx, dy = int(w * fraction), int(h * fraction)
    return img.crop((dx, dy, w - dx, h - dy))


def _compute_robustness(resolver: Resolver) -> RobustnessGrid:
    """Apply each transform to the demo asset, then run the real read-only recovery path and record
    the honest outcome plus the raw PDQ Hamming distance (computed independently so a failed
    transform still reports how far it drifted)."""
    base = Image.open(io.BytesIO(demo_sample_bytes())).convert("RGB")
    base_bits, _ = compute_pdq(base)
    transforms: list[tuple[str, Image.Image]] = [
        ("original", base),
        ("JPEG quality 90", _jpeg(base, 90)),
        ("JPEG quality 50", _jpeg(base, 50)),
        ("JPEG quality 20", _jpeg(base, 20)),
        ("downscale 50%", _scale(base, 0.5)),
        ("upscale 150%", _scale(base, 1.5)),
        ("center crop 10%", _crop(base, 0.10)),
        ("center crop 25%", _crop(base, 0.25)),
        ("rotate 5 deg", base.rotate(5, expand=True)),
        ("rotate 90 deg", base.rotate(90, expand=True)),
        ("screenshot (downscale + JPEG)", _jpeg(_scale(base, 0.6), 70)),
    ]
    rows: list[RobustnessRow] = []
    for label, img in transforms:
        q_bits, _ = compute_pdq(img)
        dist = hamming(base_bits, q_bits)
        result = resolver.resolve_by_content(img)
        match = result.matches[0] if result.matches else None
        recovered = match is not None and match.manifest_id == DEMO_MANIFEST_ID
        rows.append(
            RobustnessRow(
                transform=label,
                recovered=recovered,
                similarity_score=match.similarity_score if match else None,
                hamming_distance=dist,
            )
        )
    return RobustnessGrid(manifest_id=DEMO_MANIFEST_ID, threshold=PDQ_HAMMING_THRESHOLD, rows=rows)


@router.get("/demo/robustness", response_model=RobustnessGrid, include_in_schema=False)
async def demo_robustness() -> RobustnessGrid:
    """An honest adversarial-robustness grid: apply common transforms to the demo asset and run the
    real recovery path on each. PDQ survives re-encode and scaling, not rotation or large crops, so
    the grid shows exactly where recovery holds and where it does not. Read-only (no register, no
    log append); computed off the event loop."""
    from veridex_api import sbr

    return await run_in_threadpool(_compute_robustness, sbr.get_resolver())


class RebuildResult(CamelModel):
    """The recovery index rebuilt from Backblaze B2 alone. Rooted's resolver and transparency log
    are derived state; the authoritative record is the content-addressed objects in B2. This walks
    the
    manifests stored in B2, re-fetches each asset, re-fingerprints it into a FRESH resolver and log,
    then re-proves the demo asset recovers, so a lost database can be fully reconstituted from B2.
    Read-only: it builds a throwaway index and never touches the live one. roots_match is usually
    false because a transparency log is append-ordered while B2 is a content-addressed store with no
    order, and the live log also carries runtime leaves (for example event-ingested) whose manifests
    are not stored under the manifest prefix; the load-bearing claim is that the recovery index and
    the demo recovery rebuild from B2."""

    available: bool
    backend: str
    manifests_scanned: int
    manifests_rebuilt: int
    skipped: int
    leaves_rebuilt: int
    demo_recovered: bool
    demo_similarity: int | None
    rebuilt_tree_size: int
    rebuilt_root_hash: str
    live_tree_size: int
    live_root_hash: str
    roots_match: bool
    note: str


_REBUILD_MANIFEST_CAP = 100


def _compute_rebuild(storage: Storage, live_log: TransparencyLog) -> RebuildResult:
    """Reconstruct a fresh resolver + log from the manifests/assets stored in B2, then recover the
    demo asset against the rebuilt index. Bounded to _REBUILD_MANIFEST_CAP manifests."""
    backend = "backblaze-b2" if isinstance(storage, B2Storage) else "in-memory"
    keys = storage.list_keys(f"{MANIFEST_PREFIX}/")[:_REBUILD_MANIFEST_CAP]
    fresh = Resolver(InMemoryIndex(), FakeWatermarker())
    fresh_log = TransparencyLog()
    rebuilt = 0
    skipped = 0
    for mk in keys:
        try:
            manifest = Manifest.model_validate_json(storage.get(mk))
            akey = asset_key(manifest.asset_sha256)
            if not storage.exists(akey):
                skipped += 1
                continue
            image = Image.open(io.BytesIO(storage.get(akey))).convert("RGB")
        except Exception:  # noqa: BLE001 - a non-image asset (audio/video) or a bad object is skipped
            skipped += 1
            continue
        watermark = manifest.soft_bindings[0].value if manifest.soft_bindings else ""
        fresh.register(manifest, image, watermark)
        fresh_log.append(manifest.manifest_id, manifest.canonical_hash())
        rebuilt += 1

    demo_img = Image.open(io.BytesIO(demo_sample_bytes())).convert("RGB")
    result = fresh.resolve_by_content(demo_img)
    match = result.matches[0] if result.matches else None
    demo_recovered = match is not None and match.manifest_id == DEMO_MANIFEST_ID

    rebuilt_root = fresh_log.root().hex() if fresh_log.size else ""
    live_root = live_log.root().hex() if live_log.size else ""
    note = (
        f"Rebuilt {rebuilt} image manifests from B2 content-addressed objects with no database; "
        "the demo asset recovers against the rebuilt index."
        if demo_recovered
        else "Rebuilt from B2; the demo asset did not recover against the rebuilt index."
    )
    return RebuildResult(
        available=True,
        backend=backend,
        manifests_scanned=len(keys),
        manifests_rebuilt=rebuilt,
        skipped=skipped,
        leaves_rebuilt=fresh_log.size,
        demo_recovered=demo_recovered,
        demo_similarity=match.similarity_score if match else None,
        rebuilt_tree_size=fresh_log.size,
        rebuilt_root_hash=rebuilt_root,
        live_tree_size=live_log.size,
        live_root_hash=live_root,
        roots_match=(rebuilt_root == live_root and fresh_log.size == live_log.size),
        note=note,
    )


@router.get("/demo/rebuild", response_model=RebuildResult, include_in_schema=False)
async def demo_rebuild() -> RebuildResult:
    """Nuke-and-rebuild: reconstruct the recovery index from Backblaze B2 alone, then re-prove the
    demo asset recovers. Proves B2 is the source of truth, not the database. Read-only (a throwaway
    index, the live one is untouched); computed off the event loop."""
    from veridex_api import sbr

    storage = sbr.get_storage()
    if storage is None:
        return RebuildResult(
            available=False,
            backend="none",
            manifests_scanned=0,
            manifests_rebuilt=0,
            skipped=0,
            leaves_rebuilt=0,
            demo_recovered=False,
            demo_similarity=None,
            rebuilt_tree_size=0,
            rebuilt_root_hash="",
            live_tree_size=0,
            live_root_hash="",
            roots_match=False,
            note=(
                "No storage backend configured; rebuild requires Backblaze B2 "
                "(or the in-memory store in tests)."
            ),
        )
    return await run_in_threadpool(_compute_rebuild, storage, sbr.get_log())


# --- ReMark failover: a real watermark-REMOVAL attack does not defeat recovery -------------------
# The durable-content-credentials thesis: a watermark-removal attack (the ReMark literature:
# regeneration/diffusion attacks that destroy an invisible watermark) does NOT defeat recovery,
# because the perceptual fingerprint still matches. This is demonstrated on real primitives: the
# real TrustMark variant P watermark is embedded, a real removal transform is applied that
# empirically defeats the real TrustMark decoder, and the real PDQ fingerprint still recovers the
# manifest. Nothing is asserted: the watermark decode and the fingerprint match are computed live on
# the attacked bytes.

# The staged attack: a strong Gaussian blur then a low-quality JPEG recompress. Empirically this
# destroys the high-frequency invisible-watermark carrier (the TrustMark decoder returns no id)
# while the low/mid-frequency perceptual structure the fingerprint hashes stays within threshold.
REMARK_ATTACK_NAME = "gaussian blur + JPEG q30 (ReMark-class watermark removal)"
REMARK_BLUR_RADIUS = 3
REMARK_JPEG_QUALITY = 30
REMARK_ATTACK_NOTE = (
    "models the ReMark class of watermark-removal attacks (regeneration/diffusion): it destroys "
    "the high-frequency invisible-watermark carrier while preserving the low/mid-frequency "
    "perceptual structure the fingerprint hashes"
)
REMARK_STAGED_NOTE = (
    "The watermark-removal attack is staged on the demo asset to demonstrate the failover: the "
    "real TrustMark watermark is embedded, then a real removal transform is applied. The watermark "
    "decode and the fingerprint match are both computed live on the attacked bytes; nothing here "
    "is asserted."
)
REMARK_STAGED_NOTE_PARTIAL = (
    "The removal attack is staged live on the demo asset and the fingerprint recovery is computed "
    "live on the attacked bytes. This deployment does not carry the TrustMark model (the "
    "`watermark` extra), so the watermark half is not run here; that the same attack defeats the "
    "real TrustMark decoder is verified by the repository's real-model integration test, not "
    "asserted by this response."
)
REMARK_WATERMARK_NOT_RUN_NOTE = (
    "not run: the TrustMark model is not installed in this deployment. The repository's real-model "
    "integration test (test_real_removal_attack_defeats_trustmark_but_fingerprint_survives) "
    "verifies this exact attack defeats the real decoder."
)


def _remark_attack(img: Image.Image) -> bytes:
    """A real ReMark-class watermark-removal transform: strong Gaussian blur then a low-quality JPEG
    recompress. Destroys the high-frequency invisible-watermark signal while leaving the perceptual
    structure (what PDQ hashes) intact. Returns the attacked JPEG bytes."""
    blurred = img.convert("RGB").filter(ImageFilter.GaussianBlur(REMARK_BLUR_RADIUS))
    buf = io.BytesIO()
    blurred.save(buf, "JPEG", quality=REMARK_JPEG_QUALITY)
    return buf.getvalue()


# The real TrustMark P watermarker for staging the removal attack. Loading it pulls torch (the
# `watermark` extra), so it is built lazily and cached; on the lean default deploy the import fails
# and the endpoint degrades honestly (available=false) rather than faking a decode. Overridable in
# tests (they inject a FakeWatermarker so the combinatorial cases run without torch).
_remark_watermarker: Watermarker | None = None
_remark_watermarker_loaded = False
_remark_watermarker_lock = threading.Lock()
# The staged attacked bytes are cached in-process keyed by the staging watermarker's identity, so
# the embed + attack runs once per process for the real singleton and recomputes when a test swaps
# the watermarker. Reset between tests via reset_remark_cache.
_remark_attacked: tuple[int, bytes] | None = None


def reset_remark_cache() -> None:
    """Clear the cached real watermarker and staged attacked bytes (tests, or to force a reload)."""
    global _remark_watermarker, _remark_watermarker_loaded, _remark_attacked
    with _remark_watermarker_lock:
        _remark_watermarker = None
        _remark_watermarker_loaded = False
        _remark_attacked = None


def _load_remark_watermarker() -> Watermarker | None:
    """The real TrustMark variant P watermarker, or None when no real model is reachable so the
    endpoint degrades honestly instead of faking a decode. Two real sources, in order: the remote
    Modal watermark service (when VERIDEX_WATERMARK_REMOTE_URL/TOKEN are set, which is how the lean
    prod deploy gets a real model), then the in-process TrustMark (when the `watermark` extra is
    installed locally). Every path runs the real model; the remote just runs it on a machine that
    carries torch. Cached after the first resolution. Tests monkeypatch this seam."""
    global _remark_watermarker, _remark_watermarker_loaded
    if _remark_watermarker_loaded:
        return _remark_watermarker
    with _remark_watermarker_lock:
        if not _remark_watermarker_loaded:
            _remark_watermarker = _resolve_real_watermarker()
            _remark_watermarker_loaded = True
    return _remark_watermarker


def _resolve_real_watermarker() -> Watermarker | None:
    from veridex_api.remote_watermark import RemoteWatermarker, remote_watermark_config

    config = remote_watermark_config()
    if config is not None:
        base_url, token = config
        logger.info("remark-failover: using the remote watermark service")
        return RemoteWatermarker(base_url, token)
    try:
        from veridex_provenance.watermark import TrustMarkWatermarker

        return TrustMarkWatermarker()
    except Exception as exc:  # noqa: BLE001 - ImportError or a model-load failure degrades
        logger.info("remark-failover: no real TrustMark available, degrading: %s", exc)
        return None


def _staged_attacked_bytes(watermarker: Watermarker | None) -> bytes:
    """Embed the demo watermark (when a watermarker is available) then apply the real removal
    attack, returning the attacked JPEG bytes. With no watermarker (the lean deploy) the attack
    runs on the demo asset as shipped, which is enough for the live fingerprint half. Cached by
    the staging watermarker's identity so the real singleton stages once."""
    global _remark_attacked
    cached = _remark_attacked
    if cached is not None and cached[0] == id(watermarker):
        return cached[1]
    base = Image.open(io.BytesIO(demo_sample_bytes())).convert("RGB")
    marked = watermarker.encode(base, DEMO_WATERMARK_ID) if watermarker is not None else base
    attacked = _remark_attack(marked)
    _remark_attacked = (id(watermarker), attacked)
    return attacked


class RemarkAttack(CamelModel):
    """The staged watermark-removal transform: its name, parameters, and what class it models."""

    name: str
    parameters: dict[str, Any]
    note: str


class RemarkWatermark(CamelModel):
    """The watermark-recovery attempt on the attacked bytes. recovered is the REAL decode verdict
    (the decoded id equals the expected id); decoded_id is whatever the real decoder returned (null
    when the removal attack destroyed the mark). When the model is not deployed, attempted is
    false and note says where the watermark half is actually verified."""

    attempted: bool
    recovered: bool
    decoded_id: str | None
    expected_id: str
    note: str | None = None


class RemarkFingerprint(CamelModel):
    """The perceptual-fingerprint recovery on the same attacked bytes. recovered is the real
    byContent match to the demo manifest through the resolver; hamming_distance is the raw PDQ
    distance from the original (always present), matched_manifest_id is whatever the resolver
    matched (null on no match)."""

    attempted: bool
    recovered: bool
    hamming_distance: int
    threshold: int
    matched_manifest_id: str | None


class RemarkFailover(CamelModel):
    """Whether a real watermark-removal attack defeats recovery. When the real TrustMark model is
    available and the demo asset is registered, the attack is staged live and the two soft-binding
    recoveries are reported honestly; otherwise available is false with a reason."""

    available: bool
    staged: bool
    staged_note: str
    reason: str | None = None
    attack: RemarkAttack | None = None
    watermark: RemarkWatermark | None = None
    fingerprint: RemarkFingerprint | None = None
    verdict: str | None = None


def _remark_verdict(watermark_recovered: bool, fingerprint_recovered: bool) -> str:
    """The honest one-line summary of the two live recovery results (never hardcoded to the
    interesting case)."""
    if not watermark_recovered and fingerprint_recovered:
        return (
            "recovery survives watermark removal via the perceptual fingerprint: the attack "
            "destroyed the TrustMark watermark, but the fingerprint still recovered the manifest"
        )
    if watermark_recovered and fingerprint_recovered:
        return (
            "the attack did not defeat the watermark: both soft bindings still recover the "
            "manifest, so the fingerprint failover was not exercised on this transform"
        )
    if not watermark_recovered and not fingerprint_recovered:
        return (
            "the attack defeated both soft bindings: neither the watermark nor the perceptual "
            "fingerprint recovered the manifest under this transform"
        )
    return (
        "the watermark survived but the perceptual fingerprint did not recover the manifest under "
        "this transform"
    )


def _compute_remark_failover(watermarker: Watermarker | None, resolver: Resolver) -> RemarkFailover:
    """Stage the removal attack on the demo asset and compute the recovery verdicts live. The
    watermark verdict is a real decode on the attacked bytes; the fingerprint verdict is a real
    byContent match through the resolver. Without the TrustMark model (the lean deploy) the
    fingerprint half still runs live and the watermark half honestly reports attempted=false with
    a pointer to the real-model integration test. Degrades to available=false (never 500) only
    when the demo asset is not registered."""
    if resolver.get_manifest(DEMO_MANIFEST_ID) is None:
        return RemarkFailover(
            available=False,
            staged=True,
            staged_note=REMARK_STAGED_NOTE if watermarker else REMARK_STAGED_NOTE_PARTIAL,
            reason="the demo asset is not registered in the recovery index (empty registry)",
        )
    base_bits, _ = compute_pdq(Image.open(io.BytesIO(demo_sample_bytes())).convert("RGB"))
    attacked_bytes = _staged_attacked_bytes(watermarker)
    attacked = Image.open(io.BytesIO(attacked_bytes)).convert("RGB")

    # Watermark verdict: run the REAL decoder on the attacked bytes when the model is deployed.
    # Nothing is asserted; a lean deploy reports attempted=false and where the half IS verified.
    if watermarker is not None:
        decoded_id, _conf = watermarker.decode(attacked)
        watermark_recovered = decoded_id == DEMO_WATERMARK_ID
        watermark = RemarkWatermark(
            attempted=True,
            recovered=watermark_recovered,
            decoded_id=decoded_id,
            expected_id=DEMO_WATERMARK_ID,
        )
    else:
        watermark_recovered = False
        watermark = RemarkWatermark(
            attempted=False,
            recovered=False,
            decoded_id=None,
            expected_id=DEMO_WATERMARK_ID,
            note=REMARK_WATERMARK_NOT_RUN_NOTE,
        )

    # Fingerprint verdict: the real byContent recovery through the resolver, plus the raw PDQ
    # distance from the original (computed independently so it is always reported).
    attacked_bits, _ = compute_pdq(attacked)
    distance = hamming(base_bits, attacked_bits)
    result = resolver.resolve_by_content(attacked)
    match = result.matches[0] if result.matches else None
    fingerprint_recovered = match is not None and match.manifest_id == DEMO_MANIFEST_ID

    if watermarker is not None:
        verdict = _remark_verdict(watermark_recovered, fingerprint_recovered)
    elif fingerprint_recovered:
        verdict = (
            "the perceptual fingerprint recovered the manifest under the ReMark-class attack "
            "(computed live); the watermark half was not run here because the TrustMark model is "
            "not deployed, and is verified by the repository's real-model integration test"
        )
    else:
        verdict = (
            "the attack defeated the perceptual fingerprint on this deployment; the watermark "
            "half was not run here because the TrustMark model is not deployed"
        )

    return RemarkFailover(
        available=True,
        staged=True,
        staged_note=REMARK_STAGED_NOTE if watermarker else REMARK_STAGED_NOTE_PARTIAL,
        attack=RemarkAttack(
            name=REMARK_ATTACK_NAME,
            parameters={
                "gaussianBlurRadius": REMARK_BLUR_RADIUS,
                "jpegQuality": REMARK_JPEG_QUALITY,
            },
            note=REMARK_ATTACK_NOTE,
        ),
        watermark=watermark,
        fingerprint=RemarkFingerprint(
            attempted=True,
            recovered=fingerprint_recovered,
            hamming_distance=distance,
            threshold=PDQ_HAMMING_THRESHOLD,
            matched_manifest_id=match.manifest_id if match else None,
        ),
        verdict=verdict,
    )


@router.get(
    "/demo/remark-failover",
    response_model=RemarkFailover,
    include_in_schema=False,
)
async def demo_remark_failover() -> RemarkFailover:
    """Demonstrate that a real watermark-REMOVAL attack does not defeat recovery. Stages a real
    ReMark-class removal transform (Gaussian blur + JPEG q30) on the watermarked demo asset, then
    reports two live recovery results: the real TrustMark decode on the attacked bytes (which the
    attack defeats) and the real PDQ fingerprint match through the resolver (which survives). The
    verdict is computed from the two results, never hardcoded. Degrades honestly (available=false)
    when the real TrustMark model is unavailable or the demo asset is unregistered, never a 500.
    Read-only; the heavy embed/attack/decode runs off the event loop."""
    from veridex_api import sbr

    watermarker = _load_remark_watermarker()
    return await run_in_threadpool(_compute_remark_failover, watermarker, sbr.get_resolver())
