"""C2PA claim: sign an asset, read the credential back, confirm the soft-binding + "Valid" state.

Uses the c2pa ES256 test cert fixtures kept in the gitignored research/ dir, so this test runs
locally where the fixtures exist and skips in CI where they do not (the rest of the suite still
exercises the trust core without any embedded keys).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from veridex_provenance.claim import (
    DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA,
    SOFT_BINDING_LABEL,
    build_manifest_def,
    conformance_trust_anchors,
    conformance_trust_config,
    make_es256_signer,
    read_claim,
    sign_claim,
)
from veridex_provenance.models import ALG_TRUSTMARK_P, Manifest

_FIXTURES = Path(__file__).resolve().parents[3] / "research" / "c2pa-test-certs"
_CERT = _FIXTURES / "es256_certs.pem"
_KEY = _FIXTURES / "es256_private.key"

# The committed credentialed sample (signed with the C2PA test cert). Public, no key, so the trust
# test below runs in CI.
_SAMPLE = Path(__file__).resolve().parents[3] / "web" / "public" / "credentialed-sample.jpg"

# The signing skip is per-test (not a module-level pytestmark): only the sign+read test needs the
# private key from the gitignored research/ dir, while the conformance-trust test below needs only
# the committed public sample + anchors, so it must still run in CI.
_needs_signing_key = pytest.mark.skipif(
    not (_CERT.exists() and _KEY.exists()),
    reason="c2pa ES256 test cert fixtures not present (research/c2pa-test-certs/)",
)


def _jpeg(seed: int) -> bytes:
    arr = np.random.default_rng(seed).integers(0, 256, (256, 256, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG")
    return buf.getvalue()


@_needs_signing_key
def test_sign_and_read_c2pa_claim() -> None:
    signer = make_es256_signer(_CERT.read_text(), _KEY.read_bytes())
    manifest = Manifest(
        manifest_id="urn:c2pa:demo",
        asset_sha256="a" * 64,
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream"},
    )
    signed = sign_claim(signer, _jpeg(1), build_manifest_def(manifest, watermark_id="RT42"))
    assert len(signed) > 0

    data, state = read_claim(signed)
    # A test/self-signed cert validates the SIGNATURE ("Valid"), not the issuer ("Trusted").
    assert state == "Valid"
    active = data["active_manifest"]
    assertions = data["manifests"][active]["assertions"]
    labels = [a["label"] for a in assertions]
    # A real C2PA reader sees the STANDARD soft-binding assertion, not the old vendor-custom label.
    assert "c2pa.soft-binding" in labels
    assert "com.rooted.soft_binding" not in labels
    # c2pa-rs normalizes the actions label to c2pa.actions.v2 on read; match by prefix and confirm
    # the AI digitalSourceType survived the round trip (model=seedream) through signer and reader.
    actions = next(a for a in assertions if a["label"].startswith("c2pa.actions"))
    created = actions["data"]["actions"][0]
    assert created["digitalSourceType"] == DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA


def _actions_data(manifest_def: dict[str, Any]) -> dict[str, Any]:
    """The c2pa.actions assertion data from a built (not yet signed) manifest definition."""
    by_label = {a["label"]: a["data"] for a in manifest_def["assertions"]}
    data: dict[str, Any] = by_label["c2pa.actions"]
    return data


def test_build_manifest_def_uses_standard_soft_binding_and_marks_ai() -> None:
    # Pure structural check (no signing key needed, so it runs in CI): the emitted claim carries the
    # STANDARD c2pa.soft-binding assertion and marks AI media with the IPTC digitalSourceType.
    manifest = Manifest(
        manifest_id="urn:c2pa:ai",
        asset_sha256="a" * 64,
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream", "provider": "gmi"},
    )
    manifest_def = build_manifest_def(manifest, "RT42")
    by_label = {a["label"]: a["data"] for a in manifest_def["assertions"]}

    assert SOFT_BINDING_LABEL == "c2pa.soft-binding"
    assert "c2pa.soft-binding" in by_label
    assert "com.rooted.soft_binding" not in by_label
    soft = by_label["c2pa.soft-binding"]
    assert soft["alg"] == ALG_TRUSTMARK_P  # still the registered TrustMark variant P
    assert soft["blocks"][0]["value"] == "RT42"  # the standard {alg, blocks:[{scope, value}]} shape

    created = _actions_data(manifest_def)["actions"][0]
    assert created["action"] == "c2pa.created"
    assert created["digitalSourceType"] == DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA


def test_build_manifest_def_omits_digital_source_type_for_non_ai() -> None:
    # Honesty: with no concrete model the asset is not claimed as AI (no digitalSourceType), and an
    # explicit ai_generated=False overrides even when a model field is present (a known fixture).
    no_model = Manifest(
        manifest_id="urn:c2pa:plain",
        asset_sha256="b" * 64,
        created_at="2026-06-25T00:00:00Z",
    )
    plain = _actions_data(build_manifest_def(no_model, "RT1"))["actions"][0]
    assert "digitalSourceType" not in plain

    fixture = Manifest(
        manifest_id="urn:c2pa:fixture",
        asset_sha256="c" * 64,
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "rooted-demo-fixture"},
    )
    created = _actions_data(build_manifest_def(fixture, "RT2", ai_generated=False))["actions"][0]
    assert "digitalSourceType" not in created


@pytest.mark.skipif(not _SAMPLE.exists(), reason="credentialed sample not present")
def test_conformance_trust_list_yields_trusted_state() -> None:
    """The committed credentialed sample is "Valid" with no trust list, and the green "Trusted"
    state when validated against the C2PA conformance test trust anchors. Runs in CI: it needs only
    the public sample + the public test anchors, no signing key."""
    signed = _SAMPLE.read_bytes()

    _without, valid_state = read_claim(signed)
    assert valid_state in ("Valid", "Invalid")

    _with, trusted_state = read_claim(
        signed,
        trust_anchors=conformance_trust_anchors(),
        trust_config=conformance_trust_config(),
    )
    assert trusted_state in ("Trusted", "Invalid")
