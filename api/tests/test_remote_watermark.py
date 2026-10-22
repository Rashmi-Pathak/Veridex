"""The remote watermark client and the resolver seam that prefers it.

Network-free: the client's request shaping is exercised against a stub httpx transport, and the
resolver preference (remote when configured, else in-process, else None) is checked via env and
monkeypatch. The real remote round trip is proven separately by the live smoke against the deployed
Modal service, not in unit tests.
"""

from __future__ import annotations

import io

import httpx
import pytest
from PIL import Image

from veridex_api import demo
from veridex_api.remote_watermark import RemoteWatermarker, remote_watermark_config


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_config_is_none_unless_both_env_vars_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIDEX_WATERMARK_REMOTE_URL", raising=False)
    monkeypatch.delenv("VERIDEX_WATERMARK_REMOTE_TOKEN", raising=False)
    assert remote_watermark_config() is None

    monkeypatch.setenv("VERIDEX_WATERMARK_REMOTE_URL", "https://svc.modal.run/")
    assert remote_watermark_config() is None  # token still missing

    monkeypatch.setenv("VERIDEX_WATERMARK_REMOTE_TOKEN", "secret")
    config = remote_watermark_config()
    assert config == ("https://svc.modal.run", "secret")  # trailing slash trimmed


def test_decode_sends_token_and_multipart_and_maps_the_response() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["token"] = request.headers.get("X-Veridex-Token") or request.headers.get("X-Rooted-Token")
        seen["ctype"] = request.headers.get("Content-Type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"decodedId": "DEMO", "confidence": 1.0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    wm = RemoteWatermarker("https://svc.modal.run", "secret", client=client)
    decoded, confidence = wm.decode(Image.open(io.BytesIO(_png_bytes())))

    assert decoded == "DEMO"
    assert confidence == 1.0
    assert seen["path"] == "/decode"
    assert seen["token"] == "secret"
    assert "multipart/form-data" in str(seen["ctype"])
    assert b'name="file"' in seen["body"]  # type: ignore[operator]


def test_decode_maps_no_watermark_to_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"decodedId": None, "confidence": 0.0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    wm = RemoteWatermarker("https://svc.modal.run", "secret", client=client)
    decoded, confidence = wm.decode(Image.open(io.BytesIO(_png_bytes())))
    assert decoded is None
    assert confidence == 0.0


def test_encode_posts_the_id_and_returns_the_image_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/embed"
        assert b'name="watermark_id"' in request.content
        assert b"DEMO" in request.content
        return httpx.Response(200, content=_png_bytes(), headers={"Content-Type": "image/png"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    wm = RemoteWatermarker("https://svc.modal.run", "secret", client=client)
    out = wm.encode(Image.open(io.BytesIO(_png_bytes())), "DEMO")
    assert out.size == (16, 16)


def test_bad_status_raises_so_callers_degrade() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad token"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    wm = RemoteWatermarker("https://svc.modal.run", "secret", client=client)
    with pytest.raises(httpx.HTTPStatusError):
        wm.decode(Image.open(io.BytesIO(_png_bytes())))


def test_resolver_prefers_the_remote_service_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERIDEX_WATERMARK_REMOTE_URL", "https://svc.modal.run")
    monkeypatch.setenv("VERIDEX_WATERMARK_REMOTE_TOKEN", "secret")
    resolved = demo._resolve_real_watermarker()
    assert isinstance(resolved, RemoteWatermarker)


def test_resolver_is_none_when_nothing_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    # No remote config, and force the in-process import to fail so the honest None path is taken.
    monkeypatch.delenv("VERIDEX_WATERMARK_REMOTE_URL", raising=False)
    monkeypatch.delenv("VERIDEX_WATERMARK_REMOTE_TOKEN", raising=False)
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "veridex_provenance.watermark":
            raise ImportError("watermark extra not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert demo._resolve_real_watermarker() is None
