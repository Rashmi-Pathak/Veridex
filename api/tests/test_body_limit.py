"""The app-level request-body size guard (veridex_api.limits.LimitRequestBodyMiddleware).

An over-cap upload must be refused with a clean 413 before the body is buffered, whether the client
declares an oversized Content-Length or streams a chunked body that omits/understates its length. An
under-cap request must pass through untouched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from httpx import ASGITransport

from veridex_api.main import app


async def test_content_length_over_cap_is_413(monkeypatch: pytest.MonkeyPatch) -> None:
    # A declared Content-Length over the cap is rejected before the route runs, so even a bytes POST
    # to a JSON endpoint short-circuits to 413 (never reaching validation).
    monkeypatch.setenv("VERIDEX_MAX_REQUEST_BYTES", "1024")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/verify", content=b"x" * 4096)
    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


async def test_streamed_body_over_cap_is_413(monkeypatch: pytest.MonkeyPatch) -> None:
    # A chunked body (no Content-Length: httpx streams a generator) is caught by the running-total
    # accumulator and rejected mid-stream.
    monkeypatch.setenv("VERIDEX_MAX_REQUEST_BYTES", "1024")

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(8):
            yield b"y" * 512  # 4096 total, over the 1024 cap

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/verify", content=chunks())
    assert r.status_code == 413


async def test_under_cap_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # A small body is not blocked by the guard: it reaches FastAPI validation, which 422s an empty
    # /verify body. The point is that the middleware did NOT 413 it.
    monkeypatch.setenv("VERIDEX_MAX_REQUEST_BYTES", str(32 * 1024 * 1024))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        health = await c.get("/health")
        assert health.status_code == 200
        small = await c.post("/verify", json={})
    assert small.status_code != 413
