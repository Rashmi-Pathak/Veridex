"""Rooted's MCP server is mounted in-process at /mcp and reachable over HTTP.

The MCP product surface (verify_asset, recover_manifest, query_transparency_log) ships on the same
deploy as the SBR API, so a judge can connect their own agent to /mcp with no separate service.
These tests prove the mount exists (not a 404), a real MCP initialize handshake returns the Rooted
server, and that tools/list serves the three curated tools over HTTP. The tool logic itself (against
the live SBR routes through the in-process ASGI client) is covered in mcp/tests/test_server.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from veridex_api.main import app

_HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "rooted-test", "version": "0"},
    },
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _sse_json(text: str) -> dict[str, Any]:
    """Parse the first JSON payload out of a text/event-stream response body."""
    for line in text.splitlines():
        if line.startswith("data: "):
            return cast(dict[str, Any], json.loads(line[len("data: ") :]))
    raise AssertionError(f"no SSE data line in response: {text!r}")


def test_mcp_mount_is_reachable_not_404(client: TestClient) -> None:
    # A bare POST with no streamable-HTTP Accept header is rejected by the session manager (406),
    # not a 404: a 404 would mean the mount is missing entirely.
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code != 404, "the MCP server is not mounted at /mcp"
    assert r.status_code in {400, 406}


def test_mcp_initialize_returns_the_rooted_server(client: TestClient) -> None:
    r = client.post("/mcp", json=_INIT, headers=_HDR)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/event-stream")
    result = _sse_json(r.text)["result"]
    assert result["protocolVersion"]
    assert result["serverInfo"]["name"] == "Rooted"


def test_mcp_tools_list_serves_the_three_curated_tools(client: TestClient) -> None:
    init = client.post("/mcp", json=_INIT, headers=_HDR)
    session_id = init.headers.get("mcp-session-id")
    assert session_id, "the MCP server did not issue a session id"
    auth = {**_HDR, "mcp-session-id": session_id, "MCP-Protocol-Version": "2025-06-18"}
    client.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=auth
    )
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=auth)
    assert r.status_code == 200
    tools = {t["name"] for t in _sse_json(r.text)["result"]["tools"]}
    assert tools == {"verify_asset", "recover_manifest", "query_transparency_log"}
