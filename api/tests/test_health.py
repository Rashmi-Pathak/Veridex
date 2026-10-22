"""Smoke test for the liveness probe and the startup lifespan, against the ASGI app in-process."""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

import veridex_api.sbr as sbr
from veridex_api.main import app, lifespan


async def test_health_returns_ok() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "veridex-api"


async def test_lifespan_builds_resolver_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)  # in-memory path, no DB needed
    sbr.set_resolver(None)
    try:
        async with lifespan(app):
            assert sbr._resolver is not None  # built during startup, not lazily on first request
    finally:
        sbr.set_resolver(None)
