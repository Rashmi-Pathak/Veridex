"""C2PA SBR 2.4 proof-of-ingestion receipts: spec-shaped aliases over Rooted's real Merkle proof.

A receipt wraps the EXISTING inclusion proof (the same one GET /transparency/proof returns) in the
spec's c2pa.manifestReceipt shape. These tests prove the receipt is conformant (@context, @type,
repository, anchor), that verified is the real verification (not a hardcoded flag), that a submitted
receipt is honestly checked (true round-trip, false on a mismatched id, a wrong @type, or a tampered
proof), that the registry refuses deletion (405, WORM), and that returnReceipt on /ingest is
back-compatible.
"""

from __future__ import annotations

import io

import httpx
import numpy as np
from httpx import ASGITransport
from PIL import Image
from pymerkle import MerkleProof

from veridex_api.main import app

_RECEIPT_TYPE = "org.c2pa.manifest-receipt"


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


async def test_get_verified_receipt_is_conformant_and_really_verified() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:rcpt1", "RR01", 71)
        r = await c.get("/manifests/urn:c2pa:rcpt1/receipts")
    assert r.status_code == 200
    body = r.json()

    # The @-aliased fields serialize literally, and @type is the spec const.
    assert body["@type"] == _RECEIPT_TYPE
    assert body["@context"]["c2pa"] == "https://c2pa.org/ns/"
    assert body["@context"]["receipt"] == "https://c2pa.org/ns/manifest-receipt#"

    # repository identifies this server and the manifest.
    assert body["repository"]["manifestId"] == "urn:c2pa:rcpt1"
    assert body["repository"]["uri"] == "http://test"

    # anchor.uri points at the proof route; anchor.proof is Rooted's real inclusion proof.
    assert "/transparency/proof/" in body["anchor"]["uri"]
    proof = body["anchor"]["proof"]
    assert proof["alg"] == "sha256"
    assert proof["leafHash"]
    assert proof["checkpoint"]["signatureB64"]

    # verified is the REAL verification, and the embedded proof resolves to the signed root
    # independently (not via the server flag): this is what makes verified=true honest.
    assert body["verified"] is True
    assert "error" not in body  # omitted when verified
    merkle = MerkleProof.deserialize(proof["proof"])
    _resolve_fn = getattr(merkle, "compute_root", None) or merkle.resolve
    assert _resolve_fn() == bytes.fromhex(proof["checkpoint"]["rootHash"])
    assert proof["rootHash"] == proof["checkpoint"]["rootHash"]


async def test_get_verified_receipt_unknown_manifest_404() -> None:
    async with _client() as c:
        r = await c.get("/manifests/urn:c2pa:never-ingested/receipts")
    assert r.status_code == 404


async def test_verify_receipt_roundtrip_true() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:rcpt2", "RR02", 72)
        receipt = (await c.get("/manifests/urn:c2pa:rcpt2/receipts")).json()
        v = await c.post("/manifests/urn:c2pa:rcpt2/receipts", json=receipt)
    assert v.status_code == 200
    body = v.json()
    assert body["verified"] is True
    assert "error" not in body
    assert body["@type"] == _RECEIPT_TYPE
    assert body["repository"]["manifestId"] == "urn:c2pa:rcpt2"


async def test_verify_receipt_mismatched_path_id_is_false() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:rcpt3a", "RR3A", 73)
        await _ingest(c, "urn:c2pa:rcpt3b", "RR3B", 74)
        receipt = (await c.get("/manifests/urn:c2pa:rcpt3a/receipts")).json()
        # submit A's receipt against B's path: the repository manifestId no longer matches.
        v = await c.post("/manifests/urn:c2pa:rcpt3b/receipts", json=receipt)
    assert v.status_code == 200
    body = v.json()
    assert body["verified"] is False
    assert "manifestId" in body["error"]


async def test_verify_receipt_wrong_type_is_false() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:rcpt4", "RR04", 75)
        receipt = (await c.get("/manifests/urn:c2pa:rcpt4/receipts")).json()
        receipt["@type"] = "org.example.not-a-receipt"
        v = await c.post("/manifests/urn:c2pa:rcpt4/receipts", json=receipt)
    assert v.status_code == 200
    body = v.json()
    assert body["verified"] is False
    assert "@type" in body["error"]


async def test_verify_receipt_tampered_proof_is_false() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:rcpt5", "RR05", 76)
        receipt = (await c.get("/manifests/urn:c2pa:rcpt5/receipts")).json()
        # forge the root hash inside the supplied proof: the real recompute must reject it.
        receipt["anchor"]["proof"]["rootHash"] = "00" * 32
        v = await c.post("/manifests/urn:c2pa:rcpt5/receipts", json=receipt)
    assert v.status_code == 200
    body = v.json()
    assert body["verified"] is False
    assert body["error"]


async def test_verify_receipt_wrong_leaf_proof_is_false() -> None:
    # A receipt carrying leaf A's fields but a DIFFERENT real leaf B's audit path must be rejected.
    # Both proofs resolve to the same signed root (same tree), so resolve()==root alone would pass;
    # the proof must be bound to the CLAIMED leaf, not merely resolve to the root.
    async with _client() as c:
        await _ingest(c, "urn:c2pa:wla", "RWLA", 91)
        await _ingest(c, "urn:c2pa:wlb", "RWLB", 92)
        receipt_a = (await c.get("/manifests/urn:c2pa:wla/receipts")).json()
        receipt_b = (await c.get("/manifests/urn:c2pa:wlb/receipts")).json()
        # graft B's valid audit path into A's receipt; A's leafHash/leafIndex/root stay unchanged.
        receipt_a["anchor"]["proof"]["proof"] = receipt_b["anchor"]["proof"]["proof"]
        v = await c.post("/manifests/urn:c2pa:wla/receipts", json=receipt_a)
    assert v.status_code == 200
    body = v.json()
    assert body["verified"] is False
    assert body["error"]


async def test_verify_receipt_malformed_body_is_400() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:rcpt6", "RR06", 77)
        v = await c.post("/manifests/urn:c2pa:rcpt6/receipts", json={"not": "a receipt"})
    assert v.status_code == 400


async def test_delete_manifest_is_405_worm_refusal() -> None:
    async with _client() as c:
        await _ingest(c, "urn:c2pa:rcpt7", "RR07", 78)
        r = await c.delete("/manifests/urn:c2pa:rcpt7")
    assert r.status_code == 405
    assert r.headers["allow"] == "GET"  # RFC 9110 requires Allow on a 405
    detail = r.json()["detail"].lower()
    assert "append-only" in detail or "immutable" in detail
    assert "object lock" in detail


async def test_delete_receipts_subpath_is_405_with_allow() -> None:
    # The greedy converter extends the WORM refusal to subpaths; the Allow header must list
    # the methods the receipts resource actually supports.
    async with _client() as c:
        r = await c.delete("/manifests/urn:c2pa:rcpt7/receipts")
    assert r.status_code == 405
    assert r.headers["allow"] == "GET, POST"


async def test_get_manifest_with_newline_id_is_404_not_405() -> None:
    # A %0A (newline) in the id fails the GET catch-all's `:path` (.*) regex; if any sibling
    # route with a default `[^/]+` converter still matches the path, Starlette answers 405,
    # which the OpenAPI contract does not document for GET. Every /manifests/{id} route must
    # use the same converter so an unmatchable id falls through to a documented 404.
    async with _client() as c:
        r = await c.get("/manifests/%0Anot-a-real-id")
    assert r.status_code == 404


async def test_ingest_return_receipt_includes_manifest_receipt() -> None:
    data = _png(79)
    async with _client() as c:
        r = await c.post(
            "/ingest",
            params={"returnReceipt": "true"},
            files={"file": ("a.png", data, "image/png")},
            data={"manifest_id": "urn:c2pa:rcpt8", "watermark_id": "RR08", "model": "flux"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["manifestId"] == "urn:c2pa:rcpt8"
    # matches c2pa.manifestCreateResult: the optional receipt is present and well-formed.
    assert body["receipt"]["@type"] == _RECEIPT_TYPE
    assert body["receipt"]["repository"]["manifestId"] == "urn:c2pa:rcpt8"
    assert body["receipt"]["anchor"]["proof"]["alg"] == "sha256"
    # the base manifestReceipt carries no verification verdict.
    assert "verified" not in body["receipt"]


async def test_ingest_default_response_is_unchanged() -> None:
    data = _png(80)
    async with _client() as c:
        r = await c.post(
            "/ingest",
            files={"file": ("a.png", data, "image/png")},
            data={"manifest_id": "urn:c2pa:rcpt9", "watermark_id": "RR09", "model": "flux"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body == {"manifestId": "urn:c2pa:rcpt9"}  # no receipt key (full back-compat)


async def test_demo_receipt_falls_back_and_degrades() -> None:
    # Isolate the log + resolver so the assertions are deterministic regardless of other tests.
    from veridex_api.sbr import set_log, set_resolver
    from veridex_provenance.merkle import TransparencyLog
    from veridex_provenance.resolver import InMemoryIndex, Resolver
    from veridex_provenance.watermark import FakeWatermarker

    set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    set_log(TransparencyLog())
    try:
        async with _client() as c:
            # Empty log: a clear, labeled empty state, never a 500.
            empty = await c.get("/demo/receipt")
            assert empty.status_code == 200
            assert empty.json()["verified"] is False
            assert empty.json()["error"]

            # With one ingested manifest and the primary demo id absent, it falls back to the first
            # logged manifest and verifies for real.
            await _ingest(c, "urn:c2pa:demoFallback", "RRDF", 81)
            got = await c.get("/demo/receipt")
        assert got.status_code == 200
        body = got.json()
        assert body["@type"] == _RECEIPT_TYPE
        assert body["verified"] is True
        assert body["repository"]["manifestId"] == "urn:c2pa:demoFallback"
    finally:
        set_resolver(None)
        set_log(None)
