"""The Genblaze + Rooted reconcile surface (the dual-axis: Backblaze B2 + Genblaze).

A real Genblaze Pipeline generation (GMI Cloud seedream) was run once and its run was written to
Backblaze B2 via Genblaze's OWN ObjectStorageSink (see make_genblaze_b2_sample.py); the native
hash-verified manifest + the asset are committed as fixtures. This endpoint re-verifies the Genblaze
native manifest at request time and reconciles it with Rooted's own signed manifest over the SAME
asset bytes, making the two-layer trust model concrete and honest: Genblaze proves INTEGRITY (the
bytes match its manifest, its Mode 1), and Rooted ADDS authenticity (an Ed25519/COSE signature), the
C2PA mapping, recovery, and a transparency proof. Genblaze's signing (Mode 2) and C2PA interop
(Mode 3) are not shipped, which is why Rooted's signing layer here is load-bearing, not redundant.
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
_ASSET = _ASSETS / "genblaze-b2-asset.jpg"
_MANIFEST = _ASSETS / "genblaze-b2-manifest.json"
_MANIFEST_ID = "urn:c2pa:genblaze-b2-0000-0000-0000-000000000001"
_CREATED_AT = "2026-06-29T00:00:00Z"
# Honest provenance: the real generator (Genblaze on GMI Cloud). The prompt is withheld from the
# surfaced provenance (SB 942 personal-provenance redaction), even though it lives in the fixtures.
_PROVENANCE: dict[str, Any] = {
    "model": "seedream-5.0-lite",
    "provider": "gmicloud-image",
    "generator": "genblaze",
}


class GenblazeIntegrity(CamelModel):
    available: bool
    schema_version: str | None
    run_id: str | None
    canonical_hash: str | None
    verify_hash: bool
    output_asset_sha256: str | None
    generator: str
    mode: str
    stored_on_b2: bool


class RootedClaim(CamelModel):
    manifest_id: str
    asset_sha256: str
    system_provenance: dict[str, Any]
    signature_valid: bool
    public_key_hex: str


class GenblazeReconcileResponse(CamelModel):
    asset_sha256: str
    genblaze: GenblazeIntegrity
    rooted: RootedClaim
    reconciled: bool


def _unavailable_integrity() -> GenblazeIntegrity:
    return GenblazeIntegrity(
        available=False,
        schema_version=None,
        run_id=None,
        canonical_hash=None,
        verify_hash=False,
        output_asset_sha256=None,
        generator="genblaze",
        mode="integrity (Mode 1)",
        # A manifest we could not even parse cannot attest that its asset is on B2.
        stored_on_b2=False,
    )


def _genblaze_integrity(manifest_json: str) -> GenblazeIntegrity:
    """Parse + RE-VERIFY the native Genblaze manifest at request time (not a stored bool). Degrades
    to available=false rather than 500 if the manifest cannot be parsed."""
    try:
        from genblaze_core.models.manifest import parse_manifest

        gm = parse_manifest(json.loads(manifest_json))
        try:
            output_sha = gm.run.steps[0].assets[0].sha256
        except (AttributeError, IndexError):
            output_sha = None
        return GenblazeIntegrity(
            available=True,
            schema_version=gm.schema_version,
            run_id=gm.run.run_id,
            canonical_hash=gm.canonical_hash,
            verify_hash=bool(gm.verify_hash()),
            output_asset_sha256=output_sha,
            generator="genblaze",
            mode="integrity (Mode 1)",
            # Documented fact about this committed fixture: the run was written to B2 by Genblaze's
            # own ObjectStorageSink when the fixture was produced (see make_genblaze_b2_sample.py),
            # under a Genblaze-chosen key not in Rooted's asset_key namespace. Only asserted on the
            # happy (parsed + verified) path; the unavailable path reports False.
            stored_on_b2=True,
        )
    except Exception as exc:  # noqa: BLE001 - a demo surface must degrade, never 500
        logger.warning("genblaze manifest parse/verify failed: %s", exc)
        return _unavailable_integrity()


@router.get(
    "/demo/genblaze-manifest", response_model=GenblazeReconcileResponse, include_in_schema=False
)
async def genblaze_manifest() -> GenblazeReconcileResponse:
    """Reconcile Genblaze's native integrity manifest with Rooted's signed manifest over the same
    asset. reconciled is true only when the Genblaze manifest verifies, our signature verifies, and
    the Genblaze output asset sha256 equals our asset_sha256 equals the actual bytes' sha256."""
    from veridex_api import sbr

    try:
        data = _ASSET.read_bytes()
        manifest_json = _MANIFEST.read_text()
    except OSError as exc:
        logger.warning("genblaze fixtures unavailable: %s", exc)
        return GenblazeReconcileResponse(
            asset_sha256="",
            genblaze=_unavailable_integrity(),
            rooted=RootedClaim(
                manifest_id=_MANIFEST_ID,
                asset_sha256="",
                system_provenance=_PROVENANCE,
                signature_valid=False,
                public_key_hex=sbr._public_key_hex(),
            ),
            reconciled=False,
        )
    sha = hashlib.sha256(data).hexdigest()
    integrity = _genblaze_integrity(manifest_json)

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
    return GenblazeReconcileResponse(
        asset_sha256=sha,
        genblaze=integrity,
        rooted=RootedClaim(
            manifest_id=_MANIFEST_ID,
            asset_sha256=rooted.asset_sha256,
            system_provenance=_PROVENANCE,
            signature_valid=signature_valid,
            public_key_hex=sbr._public_key_hex(),
        ),
        reconciled=reconciled,
    )
