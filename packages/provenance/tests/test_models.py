"""Contracts: canonical hashing is deterministic and redaction-stable."""

from __future__ import annotations

from veridex_provenance.models import (
    ALG_TRUSTMARK_P,
    Manifest,
    SoftBinding,
    SupportedAlgorithms,
    canonical_json,
    sha256_hex,
)


def _manifest() -> Manifest:
    return Manifest(
        manifest_id="urn:c2pa:11111111-1111-1111-1111-111111111111",
        asset_sha256="a" * 64,
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream", "provider": "gmi"},
        personal_provenance={"prompt": "a secret prompt", "user": "maya"},
        soft_bindings=[SoftBinding(alg=ALG_TRUSTMARK_P, value="RT42")],
    )


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_hash_is_stable() -> None:
    m = _manifest()
    assert m.canonical_hash() == m.canonical_hash()
    assert m.canonical_hash() == sha256_hex(canonical_json(m.canonical_payload()))


def test_redaction_drops_personal_but_keeps_hash() -> None:
    m = _manifest()
    r = m.redacted()
    assert r.personal_provenance == {}
    assert r.system_provenance == m.system_provenance
    # The canonical hash excludes personal provenance, so redaction does not change it.
    assert r.canonical_hash() == m.canonical_hash()


def test_redaction_withholds_a_prompt_left_in_system_provenance() -> None:
    # A legacy/WORM-locked manifest carrying the prompt in SYSTEM provenance. The signed manifest
    # cannot change (its hash is sealed), so the disclosure view withholds the prompt at read time.
    m = Manifest(
        manifest_id="urn:c2pa:22222222-2222-2222-2222-222222222222",
        asset_sha256="b" * 64,
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream", "provider": "gmi", "prompt": "a secret prompt"},
    )
    r = m.redacted()
    # The disclosure withholds the prompt but keeps the rest of system provenance.
    assert "prompt" not in r.system_provenance
    assert r.system_provenance == {"model": "seedream", "provider": "gmi"}
    # The full signed manifest is unchanged: it still carries the prompt and still hashes the same,
    # so the transparency leaf, the WORM checkpoint, and /verify are unaffected.
    assert m.system_provenance["prompt"] == "a secret prompt"
    assert "prompt" in m.canonical_payload()["system_provenance"]
    # The disclosure is a read-time view, so its hash differs from the signed manifest. Expected.
    assert r.canonical_hash() != m.canonical_hash()


def test_changing_system_provenance_changes_hash() -> None:
    m = _manifest()
    m2 = m.model_copy(update={"system_provenance": {"model": "flux"}})
    assert m2.canonical_hash() != m.canonical_hash()


def test_supported_algorithms_excludes_pdq() -> None:
    algs = SupportedAlgorithms()
    assert ALG_TRUSTMARK_P in [w.alg for w in algs.watermarks]
    joined = " ".join(a.alg for a in algs.watermarks + algs.fingerprints).lower()
    assert "pdq" not in joined
