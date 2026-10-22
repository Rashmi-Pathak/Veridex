"""Transparency log routes: a signed checkpoint and a self-contained, independently-verifiable
inclusion proof for an ingested manifest.

The proof a client gets back must be verifiable WITHOUT trusting the server: it carries the
serialized pymerkle proof and the signed checkpoint (tree head) it is pinned to, plus the public
key, so the client resolves the proof to a root and checks that root is the signed head. These
tests verify client-side, not just via the server's own flag.
"""

from __future__ import annotations

import io

import httpx
import numpy as np
from httpx import ASGITransport
from PIL import Image
from pymerkle import MerkleProof, verify_consistency

from veridex_api.main import app
from veridex_provenance.merkle import verify_checkpoint
from veridex_provenance.models import Manifest, MerkleCheckpoint
from veridex_provenance.signing import load_public_key


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


async def test_checkpoint_is_signed_and_verifies() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:tlog1", "RT01", 11)
        r = await c.get("/transparency/checkpoint")
    assert r.status_code == 200
    body = r.json()
    assert body["keySource"] == "ephemeral"
    cp = MerkleCheckpoint.model_validate(body["checkpoint"])
    assert cp.tree_size >= 1
    assert cp.epoch == cp.tree_size  # epoch is tied to tree state, not a request counter
    pub = load_public_key(bytes.fromhex(body["publicKeyHex"]))
    assert verify_checkpoint(cp, pub) is True


async def test_checkpoint_get_is_idempotent() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:tlog_idem", "RT09", 19)
        first = (await c.get("/transparency/checkpoint")).json()["checkpoint"]
        second = (await c.get("/transparency/checkpoint")).json()["checkpoint"]
    # No ingest between the two reads: the signed head must be identical (a GET must not mutate it).
    assert first["epoch"] == second["epoch"]
    assert first["treeSize"] == second["treeSize"]
    assert first["rootHash"] == second["rootHash"]
    assert first["signatureB64"] == second["signatureB64"]


async def test_inclusion_proof_is_independently_verifiable() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:tlog2", "RT02", 12)
        r = await c.get("/transparency/proof/urn:c2pa:tlog2")
        manifest_body = (await c.get("/manifests/urn:c2pa:tlog2")).json()
    assert r.status_code == 200
    body = r.json()
    assert body["manifestId"] == "urn:c2pa:tlog2"
    assert body["leafIndex"] >= 1
    assert body["serverVerified"] is True

    # The proof is pinned to a signed checkpoint: its resolved root equals the signed root, and
    # that checkpoint verifies against the returned key. This is the independent (non-server) check.
    cp = MerkleCheckpoint.model_validate(body["checkpoint"])
    pub = load_public_key(bytes.fromhex(body["publicKeyHex"]))
    assert verify_checkpoint(cp, pub) is True
    proof = MerkleProof.deserialize(body["proof"])
    _resolve_fn = getattr(proof, "compute_root", None) or proof.resolve
    assert _resolve_fn() == bytes.fromhex(cp.root_hash)
    assert body["rootHash"] == cp.root_hash

    # The leaf is bound to the actual manifest: leaf_hash is the manifest's canonical hash, which
    # redaction leaves unchanged (personal provenance is excluded from canonical_payload).
    assert body["leafHash"] == Manifest.model_validate(manifest_body).canonical_hash()


async def test_inclusion_proof_does_not_resolve_to_a_wrong_root() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:tlog3", "RT03", 13)
        body = (await c.get("/transparency/proof/urn:c2pa:tlog3")).json()
    proof = MerkleProof.deserialize(body["proof"])
    _resolve_fn = getattr(proof, "compute_root", None) or proof.resolve
    assert _resolve_fn() != b"\x00" * 32


async def test_inclusion_proof_unknown_manifest_404() -> None:
    async with _client() as c:
        r = await c.get("/transparency/proof/urn:c2pa:absent")
    assert r.status_code == 404


async def test_consistency_proof_is_independently_verifiable() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:cons1", "RC01", 21)
        await _ingest(c, "urn:c2pa:cons2", "RC02", 22)
        await _ingest(c, "urn:c2pa:cons3", "RC03", 23)
        body = (await c.get("/transparency/consistency/2")).json()
    assert body["priorSize"] == 2
    assert body["treeSize"] >= 3
    assert body["serverVerified"] is True

    # Independently verify (not via the server's flag): the consistency proof links prior_root to
    # the current root, and the current root is the signed checkpoint's root.
    cp = MerkleCheckpoint.model_validate(body["checkpoint"])
    pub = load_public_key(bytes.fromhex(body["publicKeyHex"]))
    assert verify_checkpoint(cp, pub) is True
    assert body["rootHash"] == cp.root_hash
    proof = MerkleProof.deserialize(body["proof"])
    # verify_consistency raises InvalidProof if the head is not an append-only extension of prior.
    verify_consistency(bytes.fromhex(body["priorRootHash"]), bytes.fromhex(body["rootHash"]), proof)


async def test_consistency_prior_equal_size_is_trivially_consistent() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:cons_eq", "RC10", 25)
        size = (await c.get("/transparency/checkpoint")).json()["checkpoint"]["treeSize"]
        body = (await c.get(f"/transparency/consistency/{size}")).json()
    assert body["priorSize"] == size
    assert body["treeSize"] == size
    assert body["priorRootHash"] == body["rootHash"]
    assert body["serverVerified"] is True


async def test_consistency_prior_size_out_of_range_is_404() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:cons_oor", "RC09", 24)
        r_zero = await c.get("/transparency/consistency/0")
        r_big = await c.get("/transparency/consistency/999999")
    # A tree size outside 1..current never existed in the log, so it is not-found, not a 400.
    assert r_zero.status_code == 404
    assert r_big.status_code == 404


async def test_demo_consistency_proves_append_only() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:dc1", "RD01", 31)
        await _ingest(c, "urn:c2pa:dc2", "RD02", 32)
        body = (await c.get("/demo/consistency")).json()
    assert body["available"] is True
    assert body["serverVerified"] is True
    assert body["priorSize"] == body["treeSize"] - 1
    # No locked bucket in the test env: honestly reported as not WORM-sealed; the proof still holds.
    assert body["sealedInObjectLock"] is False
    assert body["backend"] == "in-memory"
