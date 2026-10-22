"""The MCP product tools wrap the SBR API: verify, recover, and audit the transparency log.

The tools talk to the SBR API over httpx; these tests point that client at the in-process FastAPI
app (ASGITransport), so the full path runs with no network and no credentials. The shared in-process
state (resolver index + transparency log) is populated by ingesting through the same app. Untrusted
input (bad base64, non-image bytes) must return a structured result, not crash the tool.
"""

from __future__ import annotations

import base64
import io
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import numpy as np
import pytest
from fastmcp import Client
from httpx import ASGITransport
from PIL import Image
from pymerkle import MerkleProof

from veridex_api.main import app
from veridex_mcp.server import SbrClient, mcp, set_client


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    img = Image.fromarray(arr).resize((64, 64)).resize((256, 256))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _asgi_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _reset_client() -> Iterator[None]:
    # Reset the module-global SBR client after every test so a fixtureless test never reuses a stale
    # (closed) client or silently opens a real network client.
    yield
    set_client(None)


@pytest.fixture
async def sbr() -> AsyncIterator[SbrClient]:
    async with _asgi_client() as client:
        instance = SbrClient(client)
        set_client(instance)
        yield instance


async def _ingest(manifest_id: str, watermark_id: str, seed: int) -> bytes:
    data = _png(seed)
    async with _asgi_client() as c:
        r = await c.post(
            "/ingest",
            files={"file": ("a.png", data, "image/png")},
            data={"manifest_id": manifest_id, "watermark_id": watermark_id, "model": "flux"},
        )
        assert r.status_code == 200
    return data


async def test_lists_three_curated_tools(sbr: SbrClient) -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == {
        "verify_asset",
        "recover_manifest",
        "query_transparency_log",
    }


async def test_verify_asset_recovers_after_ingest(sbr: SbrClient) -> None:
    data = await _ingest("urn:c2pa:mcp1", "RT21", 21)
    b64 = base64.b64encode(data).decode()
    async with Client(mcp) as client:
        result = await client.call_tool("verify_asset", {"image_base64": b64})
    assert result.data["recovered"] is True
    assert result.data["manifest_id"] == "urn:c2pa:mcp1"


async def test_verify_asset_reports_no_match(sbr: SbrClient) -> None:
    b64 = base64.b64encode(_png(999)).decode()
    async with Client(mcp) as client:
        result = await client.call_tool("verify_asset", {"image_base64": b64})
    assert result.data["recovered"] is False
    assert result.data["reason"] == "no soft-binding match"


async def test_verify_asset_rejects_malformed_base64(sbr: SbrClient) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("verify_asset", {"image_base64": "not base64!!!"})
    assert result.data["recovered"] is False
    assert "error" in result.data


async def test_verify_asset_handles_non_image_bytes(sbr: SbrClient) -> None:
    b64 = base64.b64encode(b"this is valid base64 but not an image").decode()
    async with Client(mcp) as client:
        result = await client.call_tool("verify_asset", {"image_base64": b64})
    assert result.data["recovered"] is False


async def test_verify_asset_not_recovered_when_manifest_absent() -> None:
    # A soft-binding match exists but the manifest read 404s (an inconsistent backend state). The
    # tool must not claim recovery with empty provenance.
    set_client(_MatchWithoutManifestClient())
    async with Client(mcp) as client:
        result = await client.call_tool(
            "verify_asset", {"image_base64": base64.b64encode(_png(1)).decode()}
        )
    assert result.data["recovered"] is False


async def test_recover_manifest_by_content_is_redacted(sbr: SbrClient) -> None:
    data = await _ingest("urn:c2pa:mcp2", "RT22", 22)
    b64 = base64.b64encode(data).decode()
    async with Client(mcp) as client:
        result = await client.call_tool("recover_manifest", {"image_base64": b64})
    manifest = result.data["manifest"]
    assert manifest["manifestId"] == "urn:c2pa:mcp2"


async def test_recover_manifest_by_binding(sbr: SbrClient) -> None:
    await _ingest("urn:c2pa:mcp3", "RT23", 23)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "recover_manifest", {"alg": "com.adobe.trustmark.P", "value": "RT23"}
        )
    assert result.data["recovered"] is True
    assert result.data["manifest"]["manifestId"] == "urn:c2pa:mcp3"


async def test_recover_manifest_redacts_real_personal_provenance(sbr: SbrClient) -> None:
    # Register a manifest that actually carries PII, then prove the recovered copy is redacted.
    from veridex_api.sbr import get_resolver
    from veridex_provenance.models import Manifest

    image = Image.open(io.BytesIO(_png(41))).convert("RGB")
    manifest = Manifest(
        manifest_id="urn:c2pa:mcppii",
        asset_sha256="ab",
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "flux"},
        personal_provenance={"prompt": "a secret prompt", "user": "bob"},
    )
    get_resolver().register(manifest, image, "RTmcppii")
    async with Client(mcp) as client:
        result = await client.call_tool(
            "recover_manifest", {"alg": "com.adobe.trustmark.P", "value": "RTmcppii"}
        )
    assert result.data["recovered"] is True
    assert result.data["manifest"]["systemProvenance"]["model"] == "flux"
    assert result.data["manifest"]["personalProvenance"] == {}


async def test_recover_manifest_missing_args_has_discriminator(sbr: SbrClient) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("recover_manifest", {})
    assert result.data["recovered"] is False
    assert "error" in result.data


async def test_query_transparency_log_returns_included_proof(sbr: SbrClient) -> None:
    await _ingest("urn:c2pa:mcp4", "RT24", 24)
    async with Client(mcp) as client:
        result = await client.call_tool("query_transparency_log", {"manifest_id": "urn:c2pa:mcp4"})
    assert result.data["included"] is True
    assert result.data["inclusion_proof"]["serverVerified"] is True


async def test_query_transparency_log_proof_is_independently_verifiable(sbr: SbrClient) -> None:
    await _ingest("urn:c2pa:mcp5", "RT25", 25)
    async with Client(mcp) as client:
        result = await client.call_tool("query_transparency_log", {"manifest_id": "urn:c2pa:mcp5"})
    proof_response = result.data["inclusion_proof"]
    proof = MerkleProof.deserialize(proof_response["proof"])
    _resolve_fn = getattr(proof, "compute_root", None) or proof.resolve
    assert _resolve_fn() == bytes.fromhex(proof_response["checkpoint"]["rootHash"])


async def test_query_transparency_log_absent_manifest(sbr: SbrClient) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("query_transparency_log", {"manifest_id": "urn:c2pa:none"})
    assert result.data["included"] is False


async def test_verify_asset_rejects_oversized_base64(
    sbr: SbrClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An oversized image_base64 is rejected before it is decoded (the /mcp tools are unauthed),
    # returning the structured error the tool already handles; the cap is lowered to keep it small.
    import veridex_mcp.server as server

    monkeypatch.setattr(server, "_MAX_B64_LEN", 8)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "verify_asset", {"image_base64": base64.b64encode(_png(1)).decode()}
        )
    assert result.data["recovered"] is False
    assert "error" in result.data


async def test_query_transparency_log_id_is_not_path_traversable(sbr: SbrClient) -> None:
    # A dot-segment id is percent-encoded at the client, so it 404s (no match) instead of being
    # normalized into another route like /transparency/checkpoint.
    async with Client(mcp) as client:
        result = await client.call_tool(
            "query_transparency_log", {"manifest_id": "../transparency/checkpoint"}
        )
    assert result.data["included"] is False


class _MatchWithoutManifestClient(SbrClient):
    """A client whose content query matches but whose manifest read 404s, to exercise the
    inconsistent-backend edge that the in-memory scaffold cannot produce."""

    def __init__(self) -> None:  # no httpx client needed
        pass

    async def matches_by_content(self, image: bytes) -> dict[str, Any]:
        return {"matches": [{"manifestId": "urn:c2pa:ghost", "similarityScore": 100}]}

    async def manifest(self, manifest_id: str) -> dict[str, Any] | None:
        return None
