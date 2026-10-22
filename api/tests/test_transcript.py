"""The Genblaze AssemblyAI STT transcript reconcile endpoint (Genblaze's newest connector + B2).

GET /demo/transcript re-verifies the committed native Genblaze transcript manifest at request time
and reconciles it with Rooted's signed manifest over the same transcript bytes: the Genblaze output
asset sha256, our asset_sha256, and the transcript bytes' sha256 must all agree, and both the
Genblaze canonical-hash verification and our COSE signature must hold. The transcript text and
word-level timings are disclosed.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from veridex_api.main import app


async def test_transcript_reconciles() -> None:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/demo/transcript")
    assert r.status_code == 200, r.text
    b = r.json()
    # Genblaze native transcript manifest re-verifies (Mode 1 integrity); written to B2.
    assert b["available"] is True
    assert b["genblaze"]["available"] is True
    assert b["genblaze"]["verifyHash"] is True
    assert b["genblaze"]["generator"] == "genblaze"
    # stored_on_b2 is evidence-based: it reflects the recorded B2 object keys, not a hardcode.
    assert b["genblaze"]["storedOnB2"] is True
    assert len(b["genblaze"]["b2Keys"]) == 2
    assert all(k.startswith("genblaze-transcripts/") for k in b["genblaze"]["b2Keys"])
    assert b["genblaze"]["runId"]
    assert b["genblaze"]["canonicalHash"]
    # Rooted's signature over the same transcript bytes verifies against the published key.
    assert b["rooted"]["signatureValid"] is True
    # The reconcile: Genblaze output sha == our asset sha == the transcript bytes' sha.
    assert b["assetSha256"] == b["genblaze"]["outputAssetSha256"] == b["rooted"]["assetSha256"]
    assert b["reconciled"] is True
    # The transcript content (the disclosed asset) and its word-level timings.
    assert "verifiable content provenance" in b["transcript"]
    assert b["wordCount"] > 0
    assert len(b["wordTimings"]) == b["wordCount"]
    assert b["wordTimings"][0]["word"]
    assert b["wordTimings"][0]["end"] >= b["wordTimings"][0]["start"]
    assert b["language"] == "en"
    assert b["sourceAudioUrl"] == "/demo/speech"
    # The provenance describes how the transcript was made; the STT connector is named.
    assert b["rooted"]["systemProvenance"]["provider"] == "assemblyai"
    assert b["rooted"]["systemProvenance"]["model"] == "universal-3-pro"


async def test_transcript_degrades_when_fixture_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # A missing fixture must degrade to an honest not-reconciled response, never a 500.
    from veridex_api import transcript

    monkeypatch.setattr(transcript, "_TRANSCRIPT", Path("/nonexistent/genblaze-transcript.txt"))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/demo/transcript")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["reconciled"] is False
    assert b["available"] is False


async def test_transcript_degrades_on_malformed_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A malformed manifest (valid JSON, missing the run/steps/assets structure) must degrade to
    # available=false, never a 500. Guards the parse-inside-the-try fix.
    from veridex_api import transcript

    bad = tmp_path / "bad-manifest.json"
    bad.write_text("{}")
    monkeypatch.setattr(transcript, "_MANIFEST", bad)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/demo/transcript")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is False
    assert b["reconciled"] is False
