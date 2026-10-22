"""Security review fixes for the /ingest write path and the image decoder.

- /ingest is gated by VERIDEX_INGEST_KEY (it writes to the index and the transparency log).
- a watermark id, once bound to a manifest, is immutable (a second ingest cannot re-point it).
- the watermarker logs a visible warning when it silently degrades real TrustMark -> fake.
- the image decoder rejects a decompression bomb whose declared pixel size exceeds the cap.
"""

from __future__ import annotations

import io

import httpx
import PIL.Image
import pytest
from fastapi import HTTPException
from httpx import ASGITransport
from PIL import Image

from veridex_api import sbr
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker


def _png_bytes(size: int = 16) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (123, 50, 200)).save(buf, "PNG")
    return buf.getvalue()


def _wire() -> None:
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(TransparencyLog())


def _unwire() -> None:
    sbr.set_resolver(None)
    sbr.set_log(None)


async def _ingest(
    client: httpx.AsyncClient, manifest_id: str, watermark_id: str, key: str | None
) -> httpx.Response:
    headers = {"X-Ingest-Key": key} if key is not None else {}
    return await client.post(
        "/ingest",
        files={"file": ("a.png", _png_bytes(), "image/png")},
        data={"manifest_id": manifest_id, "watermark_id": watermark_id},
        headers=headers,
    )


async def test_ingest_requires_key_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIDEX_INGEST_KEY", "s3cret")
    _wire()
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            no_key = await _ingest(c, "urn:c2pa:a", "WMA", key=None)
            assert no_key.status_code == 401
            wrong = await _ingest(c, "urn:c2pa:a", "WMA", key="nope")
            assert wrong.status_code == 401
            ok = await _ingest(c, "urn:c2pa:a", "WMA", key="s3cret")
            assert ok.status_code == 200
    finally:
        _unwire()


async def test_ingest_non_ascii_key_is_401_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    # A non-ASCII X-Ingest-Key must be a clean 401, not a 500. Sent as raw Latin-1 header bytes so
    # it reaches the handler as a non-ASCII str (hmac.compare_digest raises on those; the gate
    # compares encoded bytes to avoid it).
    monkeypatch.setenv("VERIDEX_INGEST_KEY", "s3cret")
    _wire()
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                "/ingest",
                files={"file": ("a.png", _png_bytes(), "image/png")},
                data={"manifest_id": "urn:c2pa:u", "watermark_id": "WMU"},
                # Deliberately raw Latin-1 bytes (not str) to drive the non-ASCII-header 401 path.
                headers={"X-Ingest-Key": "café-key".encode("latin-1")},  # type: ignore[arg-type]
            )
            assert r.status_code == 401
    finally:
        _unwire()


async def test_ingest_allowed_without_key_in_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIDEX_INGEST_KEY", raising=False)
    monkeypatch.delenv("VERIDEX_REQUIRE_INGEST_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    _wire()
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            ok = await _ingest(c, "urn:c2pa:demo", "WMD", key=None)
            assert ok.status_code == 200
    finally:
        _unwire()


async def test_ingest_disabled_in_prod_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIDEX_INGEST_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    _wire()
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _ingest(c, "urn:c2pa:p", "WMP", key=None)
            assert r.status_code == 503
    finally:
        _unwire()


async def test_ingest_rejects_duplicate_watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIDEX_INGEST_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    _wire()
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            first = await _ingest(c, "urn:c2pa:victim", "SHARED", key=None)
            assert first.status_code == 200
            # a new manifest carrying the SAME watermark id must not re-point the binding
            second = await _ingest(c, "urn:c2pa:attacker", "SHARED", key=None)
            assert second.status_code == 409
    finally:
        _unwire()


def test_index_watermark_binding_is_immutable() -> None:
    idx = InMemoryIndex()
    idx.put_watermark_binding("W", "urn:c2pa:first")
    idx.put_watermark_binding("W", "urn:c2pa:second")  # must NOT overwrite
    assert idx.manifest_for_watermark("W") == "urn:c2pa:first"


def test_watermarker_warns_on_missing_extra(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("VERIDEX_REAL_WATERMARK", "1")
    # Force the missing-extra path deterministically (independent of whether trustmark happens to be
    # installed): the construction raises ImportError, so _make_watermarker must fall back to the
    # fake AND log a visible warning, not silently degrade.
    import veridex_provenance.watermark as wm_mod

    def _boom(self: object) -> None:
        raise ImportError("trustmark extra not installed")

    monkeypatch.setattr(wm_mod.TrustMarkWatermarker, "__init__", _boom)
    with caplog.at_level("WARNING"):
        wm = sbr._make_watermarker()
    assert isinstance(wm, FakeWatermarker)
    assert any(
        "trustmark" in r.message.lower() or "watermark" in r.message.lower() for r in caplog.records
    )


def test_decode_rejects_decompression_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    # Set the cap so a 50x50 image (2500 px) lands in the 1x-2x band (2000 < 2500 < 4000) where
    # Pillow only WARNS and would otherwise decode. The fix promotes that warning to an error, so
    # the decoder rejects (415) rather than materializing the pixels.
    monkeypatch.setattr(PIL.Image, "MAX_IMAGE_PIXELS", 2000)
    with pytest.raises(HTTPException) as exc:
        sbr._decode_image(_png_bytes(50))
    assert exc.value.status_code == 415


async def test_ingest_rejects_unsafe_manifest_id(monkeypatch: pytest.MonkeyPatch) -> None:
    # manifest_id flows into the storage key (manifests/<id>.json); a value with '/' or '..' must be
    # rejected at the boundary (400), not silently sanitized only for ':'.
    monkeypatch.delenv("VERIDEX_INGEST_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    _wire()
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _ingest(c, "urn:c2pa:../../etc/passwd", "WMX", key=None)
            assert r.status_code == 400
    finally:
        _unwire()


async def test_ingest_rejects_unsafe_watermark_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIDEX_INGEST_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    _wire()
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _ingest(c, "urn:c2pa:ok", "bad/../id", key=None)
            assert r.status_code == 400
    finally:
        _unwire()


async def test_ingest_surfaces_transparency_append_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # If the log append fails after the manifest is registered, the caller gets a clear 500 (the
    # manifest is recoverable but lacks a proof) instead of an opaque error.
    monkeypatch.delenv("VERIDEX_INGEST_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    resolver = Resolver(InMemoryIndex(), FakeWatermarker())
    log = TransparencyLog()

    def _boom(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("log down")

    monkeypatch.setattr(log, "append", _boom)
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await _ingest(c, "urn:c2pa:zz", "WMZ", key=None)
            assert r.status_code == 500
            assert "transparency" in r.json()["detail"].lower()
    finally:
        _unwire()
