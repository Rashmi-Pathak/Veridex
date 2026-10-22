"""The Genblaze + Rooted reconcile endpoint (the dual-axis: Backblaze B2 + Genblaze).

GET /demo/genblaze-manifest re-verifies the committed native Genblaze manifest at request time and
reconciles it with Rooted's signed manifest over the same asset: the Genblaze output asset sha256,
our asset_sha256, and the actual bytes' sha256 must all agree, and both the Genblaze canonical-hash
verification and our COSE signature must hold.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from veridex_api.main import app


async def test_genblaze_manifest_reconciles() -> None:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/demo/genblaze-manifest")
    assert r.status_code == 200, r.text
    b = r.json()
    # Genblaze native manifest re-verifies (Mode 1 integrity); written to B2 by Genblaze's own sink.
    assert b["genblaze"]["available"] is True
    assert b["genblaze"]["verifyHash"] is True
    assert b["genblaze"]["generator"] == "genblaze"
    assert b["genblaze"]["storedOnB2"] is True
    assert b["genblaze"]["runId"]
    assert b["genblaze"]["canonicalHash"]
    # Rooted's signature over the same asset verifies against the published key.
    assert b["rooted"]["signatureValid"] is True
    # The reconcile: Genblaze output sha == our asset sha == the actual bytes sha.
    assert b["assetSha256"] == b["genblaze"]["outputAssetSha256"] == b["rooted"]["assetSha256"]
    assert b["reconciled"] is True
    # SB-942: the prompt is withheld from the surfaced provenance.
    assert "prompt" not in b["rooted"]["systemProvenance"]


async def test_genblaze_manifest_degrades_when_fixture_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A missing fixture must degrade to an honest not-reconciled response, never a 500.
    from veridex_api import genblaze

    monkeypatch.setattr(genblaze, "_ASSET", Path("/nonexistent/genblaze-b2-asset.jpg"))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/demo/genblaze-manifest")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["reconciled"] is False
    assert b["genblaze"]["available"] is False
