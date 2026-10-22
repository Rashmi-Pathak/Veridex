"""End-to-end ingest -> recover loop with fakes: the demo's core path, credential-free."""

from __future__ import annotations

from pathlib import Path

import pytest

from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.signing import generate_keypair, verify_manifest
from veridex_provenance.watermark import FakeWatermarker
from veridex_storage.storage import InMemoryStorage, asset_key, signature_key
from veridex_worker.generator import FakeGenerator
from veridex_worker.pipeline import IngestPipeline


def test_ingest_then_recover_end_to_end() -> None:
    storage = InMemoryStorage()
    watermarker = FakeWatermarker(decoded_id="RT01")
    resolver = Resolver(InMemoryIndex(), watermarker)
    log = TransparencyLog()
    priv, pub = generate_keypair()
    pipeline = IngestPipeline(FakeGenerator(), storage, watermarker, resolver, log, priv)

    result = pipeline.run("a white ceramic mug under studio light", watermark_id="RT01")

    # the manifest is signed, stored, and logged
    assert verify_manifest(result.cose_signature, result.manifest, pub) is True
    assert result.merkle_index == 1
    assert storage.exists(asset_key(result.manifest.asset_sha256))
    # the COSE signature is persisted to storage and verifies from there, not just caller-held
    stored_cose = storage.get(signature_key(result.manifest.manifest_id))
    assert verify_manifest(stored_cose, result.manifest, pub) is True
    assert result.manifest.personal_provenance["prompt"]  # captured, redacted later on read

    # the asset is now RECOVERABLE: the same generated (watermarked) image resolves to the manifest
    same_image = FakeGenerator().generate("a white ceramic mug under studio light").image
    recovered = resolver.resolve_by_content(same_image)
    assert recovered.matches
    assert recovered.matches[0].manifest_id == result.manifest.manifest_id


def test_two_ingests_grow_the_log() -> None:
    resolver = Resolver(InMemoryIndex(), FakeWatermarker())
    log = TransparencyLog()
    priv, _ = generate_keypair()
    pipeline = IngestPipeline(
        FakeGenerator(), InMemoryStorage(), FakeWatermarker(), resolver, log, priv
    )
    a = pipeline.run("prompt a", watermark_id="RT0A")
    b = pipeline.run("prompt b", watermark_id="RT0B")
    assert a.merkle_index == 1
    assert b.merkle_index == 2
    assert a.manifest.manifest_id != b.manifest.manifest_id


_C2PA_FIXTURES = Path(__file__).resolve().parents[2] / "research" / "c2pa-test-certs"
_CERT = _C2PA_FIXTURES / "es256_certs.pem"
_KEY = _C2PA_FIXTURES / "es256_private.key"


@pytest.mark.skipif(
    not (_CERT.exists() and _KEY.exists()),
    reason="c2pa ES256 test cert fixtures not present (research/c2pa-test-certs/)",
)
def test_pipeline_embeds_c2pa_credential() -> None:
    from veridex_provenance.claim import make_es256_signer, read_claim

    signer = make_es256_signer(_CERT.read_text(), _KEY.read_bytes())
    storage = InMemoryStorage()
    priv, _ = generate_keypair()
    pipeline = IngestPipeline(
        FakeGenerator(),
        storage,
        FakeWatermarker(),
        Resolver(InMemoryIndex(), FakeWatermarker()),
        TransparencyLog(),
        priv,
        claim_signer=signer,
    )
    result = pipeline.run("a white mug", watermark_id="RT05")
    assert result.credential_embedded is True

    # the stored circulating asset carries a readable, valid C2PA credential with the STANDARD
    # C2PA soft-binding assertion (recognizable to any third-party reader).
    data, state = read_claim(storage.get(asset_key(result.manifest.asset_sha256)))
    assert state == "Valid"
    active = data["active_manifest"]
    labels = [a["label"] for a in data["manifests"][active]["assertions"]]
    assert "c2pa.soft-binding" in labels
    assert "com.rooted.soft_binding" not in labels
