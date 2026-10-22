"""Ed25519/COSE: sign-verify round-trip, tamper detection, wrong-key rejection, redaction-stable."""

from __future__ import annotations

from veridex_provenance.models import Manifest
from veridex_provenance.signing import (
    generate_keypair,
    load_private_key,
    load_public_key,
    private_key_bytes,
    public_key_bytes,
    sign_manifest,
    verify_manifest,
)


def _manifest() -> Manifest:
    return Manifest(
        manifest_id="urn:c2pa:22222222-2222-2222-2222-222222222222",
        asset_sha256="b" * 64,
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream"},
        personal_provenance={"prompt": "secret"},
    )


def test_sign_verify_roundtrip() -> None:
    priv, pub = generate_keypair()
    m = _manifest()
    sig = sign_manifest(m, priv)
    assert verify_manifest(sig, m, pub) is True


def test_tampered_manifest_fails() -> None:
    priv, pub = generate_keypair()
    m = _manifest()
    sig = sign_manifest(m, priv)
    tampered = m.model_copy(update={"system_provenance": {"model": "evil"}})
    assert verify_manifest(sig, tampered, pub) is False


def test_malformed_input_returns_false_not_crash() -> None:
    _, pub = generate_keypair()
    m = _manifest()
    for bad in [b"", b"\x00\x01\x02", b"garbage-not-cbor", b"\xff\xff"]:
        assert verify_manifest(bad, m, pub) is False


def test_wrong_key_fails() -> None:
    priv, _ = generate_keypair()
    _, other_pub = generate_keypair()
    m = _manifest()
    sig = sign_manifest(m, priv)
    assert verify_manifest(sig, m, other_pub) is False


def test_personal_only_redaction_still_verifies() -> None:
    # The common case: the prompt is in personal_provenance, which the canonical payload excludes,
    # so clearing it leaves the signature valid. The redacted disclosure is still self-verifiable.
    priv, pub = generate_keypair()
    m = _manifest()
    sig = sign_manifest(m, priv)
    assert verify_manifest(sig, m.redacted(), pub) is True


def test_redacting_a_system_prompt_does_not_verify() -> None:
    # A legacy/WORM-locked manifest carries the prompt in SYSTEM provenance (which IS hashed). The
    # disclosure strips it, so the redacted view deliberately no longer verifies against the signed
    # manifest. This is by design: the verifiable artifact is the FULL signed manifest, not the
    # privacy disclosure. The signature still verifies against the unchanged full manifest.
    priv, pub = generate_keypair()
    m = Manifest(
        manifest_id="urn:c2pa:33333333-3333-3333-3333-333333333333",
        asset_sha256="c" * 64,
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream", "prompt": "secret"},
    )
    sig = sign_manifest(m, priv)
    # The unchanged full manifest still verifies; the redacted disclosure deliberately does not.
    assert verify_manifest(sig, m, pub) is True
    assert verify_manifest(sig, m.redacted(), pub) is False


def test_key_serialization_roundtrip() -> None:
    priv, pub = generate_keypair()
    m = _manifest()
    priv2 = load_private_key(private_key_bytes(priv))
    pub2 = load_public_key(public_key_bytes(pub))
    assert verify_manifest(sign_manifest(m, priv2), m, pub2) is True
