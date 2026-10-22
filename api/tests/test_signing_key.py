"""The checkpoint signing key. ED25519_PRIVATE_KEY_HEX carries the raw key as a single-line,
env-friendly hex string, so a deploy can pin a stable key across redeploys (key_source "configured")
instead of a per-restart ephemeral key that would invalidate earlier inclusion proofs."""

from __future__ import annotations

import pytest

from veridex_api import sbr
from veridex_provenance.signing import generate_keypair, private_key_bytes, public_key_bytes


def test_load_signing_key_from_hex(monkeypatch: pytest.MonkeyPatch) -> None:
    priv, pub = generate_keypair()
    monkeypatch.setenv("ED25519_PRIVATE_KEY_HEX", private_key_bytes(priv).hex())
    monkeypatch.delenv("ED25519_PRIVATE_KEY_PATH", raising=False)
    loaded, source = sbr._load_signing_key()
    assert source == "configured"
    # the loaded key is the same one (same public key), so checkpoints verify against the stable key
    assert public_key_bytes(loaded.public_key()) == public_key_bytes(pub)


def test_hex_tolerates_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    priv, _pub = generate_keypair()
    monkeypatch.setenv("ED25519_PRIVATE_KEY_HEX", f"  {private_key_bytes(priv).hex()}\n")
    monkeypatch.delenv("ED25519_PRIVATE_KEY_PATH", raising=False)
    _key, source = sbr._load_signing_key()
    assert source == "configured"


def test_ephemeral_when_nothing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ED25519_PRIVATE_KEY_HEX", raising=False)
    monkeypatch.delenv("ED25519_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.delenv("VERIDEX_REQUIRE_SIGNING_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    _key, source = sbr._load_signing_key()
    assert source == "ephemeral"


def test_required_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ED25519_PRIVATE_KEY_HEX", raising=False)
    monkeypatch.delenv("ED25519_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.setenv("VERIDEX_REQUIRE_SIGNING_KEY", "1")
    with pytest.raises(RuntimeError):
        sbr._load_signing_key()
