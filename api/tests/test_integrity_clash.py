"""Integrity-clash detection: the embedded C2PA claim versus the recovered registry record.

compare_provenance is pure computation, so these tests prove it names each load-bearing
contradiction (the AI-generated digitalSourceType, generator model, provider, asset hash), stays
quiet when the two layers agree (including across case and whitespace differences, the
canonical-form rule), and skips a field one side has no concrete value for rather than guessing.
The /demo/integrity-clash route is proven against a REAL ingested registry record, labeled staged
in the response shape itself, and degrading to an honest empty state when the registry or the
fixture is missing.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import httpx
import numpy as np
import pytest
from httpx import ASGITransport
from PIL import Image

from veridex_api.integrity import EmbeddedManifestSummary, compare_provenance
from veridex_api.main import app
from veridex_provenance.claim import DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA
from veridex_provenance.models import Manifest

_DIGITAL_CAPTURE = "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture"
_REAL_SHA = hashlib.sha256(b"the real asset bytes").hexdigest()
_OTHER_SHA = hashlib.sha256(b"different asset bytes").hexdigest()


def _registry_manifest(model: str = "seedream-5.0-lite", provider: str | None = None) -> Manifest:
    system: dict[str, str] = {"model": model}
    if provider is not None:
        system["provider"] = provider
    return Manifest(
        manifest_id="urn:c2pa:clash-unit",
        asset_sha256=_REAL_SHA,
        created_at="2026-06-27T00:00:00Z",
        system_provenance=system,
    )


# --- the pure comparison ---------------------------------------------------------------------


def test_forged_human_capture_claim_names_every_contradiction() -> None:
    recovered = _registry_manifest(provider="gmicloud-image")
    embedded = EmbeddedManifestSummary(
        digital_source_type=_DIGITAL_CAPTURE,
        model="example-dslr-x100",
        provider="example-camera-vendor",
        asset_sha256=_OTHER_SHA,
    )
    verdict = compare_provenance(recovered, embedded)
    assert verdict.clash is True
    fields = {c.field for c in verdict.contradictions}
    assert fields == {
        "digital_source_type",
        "system_provenance.model",
        "system_provenance.provider",
        "asset_sha256",
    }
    # each contradiction carries the two real values, not a canned string.
    dst = next(c for c in verdict.contradictions if c.field == "digital_source_type")
    assert dst.embedded == _DIGITAL_CAPTURE
    assert dst.recovered == DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA
    assert "seedream-5.0-lite" in dst.meaning
    model = next(c for c in verdict.contradictions if c.field == "system_provenance.model")
    assert model.embedded == "example-dslr-x100"
    assert model.recovered == "seedream-5.0-lite"
    sha = next(c for c in verdict.contradictions if c.field == "asset_sha256")
    assert sha.embedded == _OTHER_SHA
    assert sha.recovered == _REAL_SHA


def test_agreement_is_no_clash_even_across_canonical_forms() -> None:
    # Case and whitespace differences are canonical-form equal, so they are never a forgery.
    recovered = _registry_manifest(provider="gmicloud-image")
    embedded = EmbeddedManifestSummary(
        digital_source_type=DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA,
        model="  SeedReam-5.0-Lite ",
        provider="GMICLOUD-IMAGE",
        asset_sha256=_REAL_SHA.upper(),
    )
    verdict = compare_provenance(recovered, embedded)
    assert verdict.clash is False
    assert verdict.contradictions == []
    assert verdict.fields_compared == [
        "digital_source_type",
        "system_provenance.model",
        "system_provenance.provider",
        "asset_sha256",
    ]


def test_absent_embedded_fields_are_skipped_not_guessed() -> None:
    # Only the digital-source-type comparison is always possible; the rest need both sides.
    recovered = _registry_manifest(provider="gmicloud-image")
    embedded = EmbeddedManifestSummary(
        digital_source_type=DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA
    )
    verdict = compare_provenance(recovered, embedded)
    assert verdict.clash is False
    assert verdict.contradictions == []
    assert verdict.fields_compared == ["digital_source_type"]


def test_ai_claim_the_registry_cannot_back_is_a_clash() -> None:
    # A placeholder model ("unknown") is not a concrete generator, so the registry record does not
    # prove AI generation; an embedded trainedAlgorithmicMedia claim then contradicts it.
    recovered = _registry_manifest(model="unknown")
    embedded = EmbeddedManifestSummary(
        digital_source_type=DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA
    )
    verdict = compare_provenance(recovered, embedded)
    assert verdict.clash is True
    assert [c.field for c in verdict.contradictions] == ["digital_source_type"]
    assert "names no generative model" in verdict.contradictions[0].meaning
    # the placeholder model is also excluded from the model comparison (nothing concrete to diff).
    assert verdict.fields_compared == ["digital_source_type"]


# --- the /demo/integrity-clash route ---------------------------------------------------------


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    img = Image.fromarray(arr).resize((64, 64)).resize((256, 256))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _ingest(c: httpx.AsyncClient, manifest_id: str, watermark_id: str, seed: int) -> bytes:
    data = _png(seed)
    r = await c.post(
        "/ingest",
        files={"file": ("a.png", data, "image/png")},
        data={"manifest_id": manifest_id, "watermark_id": watermark_id, "model": "seedream"},
    )
    assert r.status_code == 200
    return data


def _isolated_state() -> None:
    from veridex_api.sbr import set_log, set_resolver
    from veridex_provenance.merkle import TransparencyLog
    from veridex_provenance.resolver import InMemoryIndex, Resolver
    from veridex_provenance.watermark import FakeWatermarker

    set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    set_log(TransparencyLog())


def _reset_state() -> None:
    from veridex_api.sbr import set_log, set_resolver

    set_resolver(None)
    set_log(None)


async def test_demo_integrity_clash_computes_the_verdict_on_a_real_registry_record() -> None:
    _isolated_state()
    try:
        async with _client() as c:
            data = await _ingest(c, "urn:c2pa:clash1", "CL01", 91)
            r = await c.get("/demo/integrity-clash")
        assert r.status_code == 200
        body = r.json()

        # staged labeling lives in the response shape itself.
        assert body["staged"] is True
        assert "staged" in body["stagedNote"]
        assert body["available"] is True

        # the recovered side is the real ingested registry record (disclosed view).
        assert body["manifestId"] == "urn:c2pa:clash1"
        assert body["recovered"]["systemProvenance"]["model"] == "seedream"
        assert body["recovered"]["assetSha256"] == hashlib.sha256(data).hexdigest()

        # the embedded side is the staged fixture's forged human-capture claim.
        assert body["embedded"]["digitalSourceType"] == _DIGITAL_CAPTURE
        assert body["embedded"]["model"] == "example-dslr-x100"

        # the verdict is computed over those two inputs.
        verdict = body["verdict"]
        assert verdict["clash"] is True
        fields = {c_["field"] for c_ in verdict["contradictions"]}
        assert fields == {"digital_source_type", "system_provenance.model", "asset_sha256"}
        model = next(
            c_ for c_ in verdict["contradictions"] if c_["field"] == "system_provenance.model"
        )
        assert model["embedded"] == "example-dslr-x100"
        assert model["recovered"] == "seedream"
        # the ingested record names no provider, so that field is skipped, not guessed.
        assert verdict["fieldsCompared"] == [
            "digital_source_type",
            "system_provenance.model",
            "asset_sha256",
        ]
        assert "contradiction" in body["note"]
    finally:
        _reset_state()


async def test_demo_integrity_clash_empty_registry_degrades_honestly() -> None:
    _isolated_state()
    try:
        async with _client() as c:
            r = await c.get("/demo/integrity-clash")
        assert r.status_code == 200
        body = r.json()
        assert body["staged"] is True
        assert body["available"] is False
        assert body["verdict"] is None
        assert body["recovered"] is None
        assert "registry" in body["note"]
        # the staged fixture itself still loads; only the registry side is missing.
        assert body["embedded"]["digitalSourceType"] == _DIGITAL_CAPTURE
    finally:
        _reset_state()


async def test_demo_integrity_clash_missing_fixture_degrades_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veridex_api import integrity

    monkeypatch.setattr(integrity, "_FIXTURE_PATH", Path("/nonexistent/integrity-clash.json"))
    _isolated_state()
    try:
        async with _client() as c:
            await _ingest(c, "urn:c2pa:clash2", "CL02", 92)
            r = await c.get("/demo/integrity-clash")
        assert r.status_code == 200
        body = r.json()
        assert body["staged"] is True
        assert body["available"] is False
        assert body["embedded"] is None
        assert body["verdict"] is None
        assert "fixture" in body["note"]
    finally:
        _reset_state()
