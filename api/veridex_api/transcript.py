"""The Genblaze AssemblyAI STT transcript reconcile surface (Genblaze's newest connector + B2).

A real AI speech clip (Rooted's /demo/speech, an ElevenLabs clip) was transcribed once by Genblaze's
AssemblyAI speech-to-text connector (see make_genblaze_transcript_sample.py): the connector consumes
the audio URL and produces a hash-verified TEXT transcript with word-level timings. The native
manifest + the plain transcript are committed as fixtures, and the run was persisted to Backblaze B2
via Genblaze's own S3 backend. This endpoint re-verifies the Genblaze transcript manifest at request
time and reconciles it with Rooted's own signed manifest over the SAME transcript bytes: Genblaze
proves the transcript's INTEGRITY (Mode 1), Rooted ADDS the Ed25519/COSE signature and the C2PA
claim. The transcript (text + word timings) is disclosed; the audio source is named. One artifact,
three axes: AI-generated audio, Genblaze's newest connector, and Backblaze B2 storage.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from veridex_provenance.models import CamelModel, Manifest
from veridex_provenance.signing import sign_manifest, verify_manifest

router = APIRouter()
logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent / "assets"
_MANIFEST = _ASSETS / "genblaze-transcript-manifest.json"
_TRANSCRIPT = _ASSETS / "genblaze-transcript.txt"
# The B2 object keys the builder recorded after persisting the transcript run to Backblaze. Their
# presence here is the evidence for stored_on_b2 (not a bare hardcoded claim).
_B2_RECORD = _ASSETS / "genblaze-transcript-b2.json"
_MANIFEST_ID = "urn:c2pa:genblaze-transcript-0000-0000-0000-000000000001"
_CREATED_AT = "2026-06-29T00:00:00Z"
_SOURCE_AUDIO_URL = "/demo/speech"
# The transcript's provenance: how it was made (Genblaze's AssemblyAI STT connector over our speech
# clip). No prompt exists (the input is audio); the transcript text is the disclosed asset content.
_PROVENANCE: dict[str, Any] = {
    "model": "universal-3-pro",
    "provider": "assemblyai",
    "generator": "genblaze",
    "kind": "transcript",
    "language": "en",
    "sourceAudio": _SOURCE_AUDIO_URL,
}


class WordTiming(CamelModel):
    word: str
    start: float
    end: float
    confidence: float | None = None


class GenblazeTranscriptIntegrity(CamelModel):
    available: bool
    schema_version: str | None
    run_id: str | None
    canonical_hash: str | None
    verify_hash: bool
    output_asset_sha256: str | None
    generator: str
    mode: str
    stored_on_b2: bool
    b2_keys: list[str] = []


class RootedTranscriptClaim(CamelModel):
    manifest_id: str
    asset_sha256: str
    system_provenance: dict[str, Any]
    signature_valid: bool
    public_key_hex: str


class TranscriptReconcileResponse(CamelModel):
    available: bool
    transcript: str
    word_count: int
    word_timings: list[WordTiming]
    language: str | None
    audio_duration: int | None
    source_audio_url: str
    asset_sha256: str
    genblaze: GenblazeTranscriptIntegrity
    rooted: RootedTranscriptClaim
    reconciled: bool


def _b2_object_keys() -> list[str]:
    """The B2 object keys the builder recorded after persisting the transcript run to Backblaze.
    Their presence is the evidence for stored_on_b2; empty if the run was not persisted."""
    try:
        rec = json.loads(_B2_RECORD.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    keys = [rec.get("manifestKey"), rec.get("transcriptKey")]
    return [k for k in keys if isinstance(k, str) and k]


def _unavailable_integrity() -> GenblazeTranscriptIntegrity:
    return GenblazeTranscriptIntegrity(
        available=False,
        schema_version=None,
        run_id=None,
        canonical_hash=None,
        verify_hash=False,
        output_asset_sha256=None,
        generator="genblaze",
        mode="integrity (Mode 1)",
        stored_on_b2=False,
        b2_keys=[],
    )


def _integrity(
    manifest_json: str,
) -> tuple[GenblazeTranscriptIntegrity, list[WordTiming], dict[str, Any]]:
    """Parse + RE-VERIFY the native Genblaze transcript manifest at request time. Returns the
    integrity record, the word timings, and the asset metadata (language, duration). Degrades to
    available=false (never a 500) on ANY parse/validation failure."""
    try:
        from genblaze_core.models.manifest import parse_manifest

        raw = json.loads(manifest_json)
        asset = raw["run"]["steps"][0]["assets"][0]
        timings = [WordTiming(**w) for w in asset.get("audio", {}).get("word_timings", [])]
        meta = asset.get("metadata", {})
        gm = parse_manifest(raw)
        b2_keys = _b2_object_keys()
        integrity = GenblazeTranscriptIntegrity(
            available=True,
            schema_version=gm.schema_version,
            run_id=gm.run.run_id,
            canonical_hash=gm.canonical_hash,
            verify_hash=bool(gm.verify_hash()),
            output_asset_sha256=asset.get("sha256"),
            generator="genblaze",
            mode="integrity (Mode 1)",
            stored_on_b2=bool(b2_keys),
            b2_keys=b2_keys,
        )
        return integrity, timings, meta
    except Exception as exc:  # noqa: BLE001 - a demo surface must degrade, never 500
        logger.warning("genblaze transcript manifest parse/verify failed: %s", exc)
        return _unavailable_integrity(), [], {}


@router.get("/demo/transcript", response_model=TranscriptReconcileResponse, include_in_schema=False)
async def transcript() -> TranscriptReconcileResponse:
    """Reconcile Genblaze's native transcript-integrity manifest with Rooted's signed manifest over
    the same transcript bytes. reconciled is true only when the Genblaze manifest verifies, our
    signature verifies, and the Genblaze output asset sha256 equals our asset_sha256 equals the
    transcript bytes' sha256."""
    from veridex_api import sbr

    try:
        text = _TRANSCRIPT.read_text()
        manifest_json = _MANIFEST.read_text()
    except OSError as exc:
        logger.warning("genblaze transcript fixtures unavailable: %s", exc)
        return TranscriptReconcileResponse(
            available=False,
            transcript="",
            word_count=0,
            word_timings=[],
            language=None,
            audio_duration=None,
            source_audio_url=_SOURCE_AUDIO_URL,
            asset_sha256="",
            genblaze=_unavailable_integrity(),
            rooted=RootedTranscriptClaim(
                manifest_id=_MANIFEST_ID,
                asset_sha256="",
                system_provenance=_PROVENANCE,
                signature_valid=False,
                public_key_hex=sbr._public_key_hex(),
            ),
            reconciled=False,
        )

    sha = hashlib.sha256(text.encode()).hexdigest()
    integrity, timings, meta = _integrity(manifest_json)

    rooted = Manifest(
        manifest_id=_MANIFEST_ID,
        asset_sha256=sha,
        created_at=_CREATED_AT,
        system_provenance=_PROVENANCE,
        soft_bindings=[],
    )
    cose = sign_manifest(rooted, sbr._signing_key)
    signature_valid = verify_manifest(cose, rooted, sbr.signing_public_key())

    reconciled = bool(
        integrity.available
        and integrity.verify_hash
        and signature_valid
        and integrity.output_asset_sha256 == sha == rooted.asset_sha256
    )
    return TranscriptReconcileResponse(
        available=integrity.available,
        transcript=text,
        word_count=len(timings),
        word_timings=timings,
        language=meta.get("language"),
        audio_duration=meta.get("audio_duration"),
        source_audio_url=_SOURCE_AUDIO_URL,
        asset_sha256=sha,
        genblaze=integrity,
        rooted=RootedTranscriptClaim(
            manifest_id=_MANIFEST_ID,
            asset_sha256=rooted.asset_sha256,
            system_provenance=_PROVENANCE,
            signature_valid=signature_valid,
            public_key_hex=sbr._public_key_hex(),
        ),
        reconciled=reconciled,
    )
