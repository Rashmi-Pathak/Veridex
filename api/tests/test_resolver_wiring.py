"""The SBR API resolver runs on Postgres when DATABASE_URL is set.

DATABASE_URL selects PostgresIndex (the live recovery path runs on Postgres); without it the
in-memory index keeps the demo credential-free. The Postgres path is exercised for real via a
pgserver-bundled Postgres (no Docker, no credentials), including a full ingest -> recover round-trip
through the HTTP API.
"""

from __future__ import annotations

import io
import os
import tempfile
from collections.abc import Iterator

import httpx
import numpy as np
import pytest
from httpx import ASGITransport
from PIL import Image

from veridex_api.main import app
from veridex_api.sbr import _make_resolver, _psycopg_url, set_resolver
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker
from veridex_storage.index import PostgresIndex

try:
    import pgserver
except Exception:  # pragma: no cover - platform without a pgserver wheel
    pgserver = None  # type: ignore[assignment]


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    img = Image.fromarray(arr).resize((64, 64)).resize((256, 256))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(scope="module")
def _conninfo() -> Iterator[str]:
    url = os.environ.get("VERIDEX_TEST_DATABASE_URL")
    if url:
        yield url
        return
    if pgserver is None:
        pytest.skip(
            "set VERIDEX_TEST_DATABASE_URL or install pgserver to run the Postgres wiring test"
        )
    server = pgserver.get_server(tempfile.mkdtemp())
    try:
        yield server.get_uri()
    finally:
        server.cleanup()


def test_psycopg_url_normalizes_async_scheme() -> None:
    assert _psycopg_url("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert _psycopg_url("postgresql+psycopg://u@h/db") == "postgresql://u@h/db"
    assert _psycopg_url("postgresql://u@h/db") == "postgresql://u@h/db"


def test_make_resolver_uses_inmemory_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    resolver = _make_resolver()
    assert isinstance(resolver._index, InMemoryIndex)


def test_make_resolver_uses_postgres_with_database_url(
    monkeypatch: pytest.MonkeyPatch, _conninfo: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", _conninfo)
    resolver = _make_resolver()
    assert isinstance(resolver._index, PostgresIndex)
    resolver._index.close()


async def test_live_recovery_runs_on_postgres(_conninfo: str) -> None:
    pg = PostgresIndex(_conninfo)
    pg.create_schema()
    pg.clear()
    set_resolver(Resolver(pg, FakeWatermarker()))
    try:
        data = _png(55)
        async with _client() as c:
            ing = await c.post(
                "/ingest",
                files={"file": ("a.png", data, "image/png")},
                data={
                    "manifest_id": "urn:c2pa:pgwire",
                    "watermark_id": "RT55",
                    "model": "seedream",
                },
            )
            assert ing.status_code == 200
            rec = await c.post("/matches/byContent", files={"file": ("a.png", data, "image/png")})
            man = await c.get("/manifests/urn:c2pa:pgwire")
        assert rec.json()["matches"][0]["manifestId"] == "urn:c2pa:pgwire"
        assert man.json()["systemProvenance"]["model"] == "seedream"
    finally:
        set_resolver(None)
        pg.close()
