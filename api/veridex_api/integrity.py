"""Integrity-clash detection: the embedded C2PA claim versus the recovered registry record.

Rooted holds two provenance layers for an asset: the manifest EMBEDDED in the file (which anyone
can strip, replace, or forge) and the registry record RECOVERED by watermark or fingerprint (which
is signed and anchored in the transparency log). When the two disagree on a load-bearing field,
that disagreement is evidence of laundered or forged provenance, and Rooted names it field by
field instead of returning a bare boolean. The comparison here is pure computation over the two
inputs; nothing in a verdict is hardcoded.

Compared fields (load-bearing only): whether the asset is AI-generated (an IPTC digitalSourceType
of trainedAlgorithmicMedia versus a concrete generative model in the registry record), the
generator model, the provider, and the asset SHA-256 when the embedded claim carries one. Values
are diffed in canonical form (trimmed, casefolded text; lowercased hex), never str() reprs, so a
case or whitespace difference is not reported as a forgery.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from veridex_provenance.claim import (
    _NON_GENERATOR_MODELS,
    DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA,
    _is_ai_generated,
)
from veridex_provenance.models import CamelModel, Manifest

logger = logging.getLogger(__name__)

# The staged embedded-manifest fixture: a forged human-capture claim for the AI-generated demo
# asset. It exists to demonstrate the attack; every response built from it is labeled staged.
_FIXTURE_PATH = Path(__file__).parent / "assets" / "integrity-clash-embedded.json"

STAGED_NOTE = (
    "The embedded/claimed provenance is a staged attack-demonstration fixture (a forged "
    "human-capture claim), not read from a live asset. The recovered registry record and the "
    "verdict are computed for real."
)

_ABSENT = "(absent)"


class EmbeddedManifestSummary(CamelModel):
    """The load-bearing summary of an asset's embedded (in-file) C2PA manifest.

    digital_source_type is the IPTC IRI from the c2pa.created action, absent when the manifest
    declares none. model and provider are the generator claims, asset_sha256 the hash the manifest
    binds to. claim_generator names the tool that wrote the manifest (informational, not compared).
    """

    digital_source_type: str | None = None
    model: str | None = None
    provider: str | None = None
    asset_sha256: str | None = None
    claim_generator: str | None = None


class Contradiction(CamelModel):
    """One named disagreement between the embedded claim and the recovered registry record."""

    field: str
    embedded: str
    recovered: str
    meaning: str


class ClashVerdict(CamelModel):
    """The computed verdict: whether the two provenance layers contradict, and exactly where.

    fields_compared lists the fields a comparison was actually possible for: a field with no
    concrete value on one side is skipped, never guessed, so an absent embedded provider is not a
    contradiction. The digital-source-type comparison is always possible (absence itself is the
    non-AI claim)."""

    clash: bool
    contradictions: list[Contradiction]
    fields_compared: list[str]


class IntegrityClashResponse(CamelModel):
    """The /demo/integrity-clash surface. staged and staged_note label the embedded summary as the
    staged fixture in the response shape itself, so staged data is never presented as live. When
    the registry or the fixture is unavailable, available is false and note says why (never 500).
    """

    staged: bool
    staged_note: str
    available: bool
    manifest_id: str | None = None
    recovered: Manifest | None = None
    embedded: EmbeddedManifestSummary | None = None
    verdict: ClashVerdict | None = None
    note: str


def _canon_text(value: Any) -> str | None:
    """Canonical comparison form for a free-text field: trimmed and casefolded, or None when the
    value is missing, not a string, or a placeholder that names nothing concrete. The placeholder
    set is the claim module's, so the two layers agree on what counts as a concrete generator."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if trimmed.lower() in _NON_GENERATOR_MODELS:
        return None
    return trimmed.casefold()


def _canon_hex(value: Any) -> str | None:
    """Canonical comparison form for a hex digest: trimmed and lowercased, or None when absent."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def _display(value: Any) -> str:
    """The human-readable form of a compared value: the trimmed original, or a labeled absence."""
    if not isinstance(value, str) or not value.strip():
        return _ABSENT
    return value.strip()


def compare_provenance(recovered: Manifest, embedded: EmbeddedManifestSummary) -> ClashVerdict:
    """Compare an embedded C2PA claim against the recovered registry record, field by field.

    The verdict is computed from the two inputs: clash is true exactly when at least one
    load-bearing field contradicts. The AI-generated comparison is semantic: an embedded manifest
    without the trainedAlgorithmicMedia digitalSourceType claims a non-AI source, which contradicts
    a registry record naming a concrete generative model (the laundering case), and the reverse
    forgery (an AI claim the registry cannot back) is flagged too. model, provider, and asset hash
    are compared only when both sides carry a concrete value.
    """
    system = recovered.system_provenance
    contradictions: list[Contradiction] = []
    fields_compared: list[str] = ["digital_source_type"]

    recovered_ai = _is_ai_generated(system)
    embedded_ai = embedded.digital_source_type == DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA
    if embedded_ai != recovered_ai:
        if recovered_ai:
            recovered_display = DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA
            meaning = (
                "The embedded manifest does not declare AI generation, but the recovered registry "
                f"record proves the asset was generated by {_display(system.get('model'))}."
            )
        else:
            recovered_display = "(no generative model in the registry record)"
            meaning = (
                "The embedded manifest declares AI generation, but the recovered registry record "
                "names no generative model."
            )
        contradictions.append(
            Contradiction(
                field="digital_source_type",
                embedded=_display(embedded.digital_source_type),
                recovered=recovered_display,
                meaning=meaning,
            )
        )

    emb_model = _canon_text(embedded.model)
    rec_model = _canon_text(system.get("model"))
    if emb_model is not None and rec_model is not None:
        fields_compared.append("system_provenance.model")
        if emb_model != rec_model:
            contradictions.append(
                Contradiction(
                    field="system_provenance.model",
                    embedded=_display(embedded.model),
                    recovered=_display(system.get("model")),
                    meaning=(
                        "The embedded manifest names a different generator model than the "
                        "registry record recovered for this asset."
                    ),
                )
            )

    emb_provider = _canon_text(embedded.provider)
    rec_provider = _canon_text(system.get("provider"))
    if emb_provider is not None and rec_provider is not None:
        fields_compared.append("system_provenance.provider")
        if emb_provider != rec_provider:
            contradictions.append(
                Contradiction(
                    field="system_provenance.provider",
                    embedded=_display(embedded.provider),
                    recovered=_display(system.get("provider")),
                    meaning=(
                        "The embedded manifest names a different provider than the registry "
                        "record recovered for this asset."
                    ),
                )
            )

    emb_hash = _canon_hex(embedded.asset_sha256)
    rec_hash = _canon_hex(recovered.asset_sha256)
    if emb_hash is not None and rec_hash is not None:
        fields_compared.append("asset_sha256")
        if emb_hash != rec_hash:
            contradictions.append(
                Contradiction(
                    field="asset_sha256",
                    embedded=_display(embedded.asset_sha256),
                    recovered=_display(recovered.asset_sha256),
                    meaning=(
                        "The embedded manifest is bound to different asset bytes than the "
                        "registry record: this manifest does not belong to this asset."
                    ),
                )
            )

    return ClashVerdict(
        clash=bool(contradictions),
        contradictions=contradictions,
        fields_compared=fields_compared,
    )


def load_staged_embedded_summary() -> EmbeddedManifestSummary | None:
    """Read the staged embedded-claim fixture, or None when it is missing or malformed (the route
    degrades to a labeled empty state, never a 500). Read per call, not cached: the file is tiny
    and tests point the path elsewhere."""
    try:
        data = json.loads(_FIXTURE_PATH.read_text())
        return EmbeddedManifestSummary.model_validate(data)
    except (OSError, ValueError) as exc:
        logger.warning("integrity-clash: staged embedded-claim fixture unavailable: %s", exc)
        return None
