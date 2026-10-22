"""Genblaze v0.6.0 byte-level output verification (`genblaze verify --fetch`).

GET /demo/genblaze-verify re-verifies the committed native Genblaze manifest (Mode 1, the fuller
verification_report: canonical hash + every output's sha256 + in-spec metadata) and compares the
asset bytes to the manifest's committed sha256 and size. B2 is not configured in the test
environment, so the byte source is the committed content-addressed copy; the check is real either
way, and the endpoint degrades to available=false rather than 500.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from veridex_api.main import app


async def test_genblaze_verify_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the committed-copy path so the test is hermetic (no network to B2).
    monkeypatch.setattr("veridex_api.byo._presign_config", lambda: None)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/demo/genblaze-verify")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is True
    # genblaze-core's Mode 1 verification (the fuller v0.6.0-era report).
    assert b["hashOk"] is True
    assert b["outputsAllSha256"] is True
    assert b["metadataInSpec"] is True
    assert b["manifestVerified"] is True
    # The byte-level check `genblaze verify --fetch` added: bytes hash to the committed sha256.
    assert b["byteSource"] == "fixture"
    assert b["byteVerified"] is True
    assert b["sizeVerified"] is True
    assert b["declaredSha256"] == b["fetchedSha256"]
    assert b["declaredSizeBytes"] == b["fetchedSizeBytes"]
    assert b["verified"] is True
    # The live genblaze-core is the v0.6.0 train (0.3.7+), and the asset lives on B2.
    assert b["genblazeVersion"]
    assert b["assetHost"] and "backblazeb2.com" in b["assetHost"]


async def test_genblaze_verify_degrades_when_manifest_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A missing manifest fixture must degrade to an honest response, never a 500.
    from veridex_api import genblaze_verify

    monkeypatch.setattr(
        genblaze_verify, "_MANIFEST", Path("/nonexistent/genblaze-b2-manifest.json")
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/demo/genblaze-verify")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is False
    assert b["verified"] is False
    assert b["byteSource"] == "none"


async def test_genblaze_verify_degrades_when_asset_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Manifest present, asset bytes missing (and B2 unconfigured): the manifest still verifies but
    # the byte-level check cannot run, so verified is false and byte_source is none.
    from veridex_api import genblaze_verify

    monkeypatch.setattr("veridex_api.byo._presign_config", lambda: None)
    monkeypatch.setattr(genblaze_verify, "_ASSET", Path("/nonexistent/genblaze-b2-asset.jpg"))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/demo/genblaze-verify")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is True
    assert b["manifestVerified"] is True
    assert b["byteSource"] == "none"
    assert b["byteVerified"] is False
    assert b["verified"] is False
