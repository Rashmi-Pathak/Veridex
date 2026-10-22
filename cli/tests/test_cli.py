"""The Rooted SBR CLI, with the API mocked (respx) so tests are deterministic and network-free."""

from __future__ import annotations

from pathlib import Path

import respx
from httpx import Response
from typer.testing import CliRunner

from veridex_cli.main import DEFAULT_API, app

runner = CliRunner()


@respx.mock
def test_recover_renders_verified(tmp_path: Path) -> None:
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8jpeg")
    respx.post(f"{DEFAULT_API}/matches/byContent").mock(
        return_value=Response(
            200, json={"matches": [{"manifestId": "urn:c2pa:demo", "similarityScore": 100}]}
        )
    )
    respx.get(f"{DEFAULT_API}/manifests/urn:c2pa:demo").mock(
        return_value=Response(
            200,
            json={
                "createdAt": "2026-06-27T00:00:00Z",
                "systemProvenance": {"model": "seedream-5.0-lite"},
            },
        )
    )
    result = runner.invoke(app, ["recover", str(img)])
    assert result.exit_code == 0, result.output
    assert "RECOVERED" in result.output
    assert "similarity 100/100" in result.output
    assert "seedream-5.0-lite" in result.output


@respx.mock
def test_recover_no_match_exits_1(tmp_path: Path) -> None:
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8")
    respx.post(f"{DEFAULT_API}/matches/byContent").mock(
        return_value=Response(200, json={"matches": []})
    )
    result = runner.invoke(app, ["recover", str(img)])
    assert result.exit_code == 1
    assert "not in the registry" in result.output


@respx.mock
def test_status_shows_recovery_index() -> None:
    respx.get(f"{DEFAULT_API}/status").mock(
        return_value=Response(
            200,
            json={
                "recoveryIndex": "postgres+hnsw",
                "transparency": {"treeSize": 12, "keySource": "configured"},
                "recoverySelfTest": {"recovered": True, "similarityScore": 100},
            },
        )
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "postgres+hnsw" in result.output
    assert "12 leaves" in result.output
