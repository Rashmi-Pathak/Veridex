"""GenblazeGenerator: the network-free logic (cross-provider fallback + asset-byte reading).

The real provider calls (GMICloud, OpenAI) are exercised by an opt-in live smoke that costs money
and needs keys, not here. genblaze is imported lazily inside the provider methods, so these tests
run without the genblaze extra installed.
"""

from __future__ import annotations

import io
import os
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import numpy as np
import pytest
from PIL import Image

from veridex_worker.generator import (
    AssetFetchError,
    GenblazeGenerator,
    GenerationResult,
    _asset_bytes,
    _fallback_exception_types,
    _validated_addresses,
)


def _png_bytes(seed: int) -> bytes:
    arr = np.random.default_rng(seed).integers(0, 256, (32, 32, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def _result(model: str, provider: str) -> GenerationResult:
    return GenerationResult(
        image=Image.new("RGB", (8, 8)), image_bytes=b"x", model=model, provider=provider
    )


def _gai_record(ip: str, port: int) -> tuple[Any, ...]:
    """A getaddrinfo result row for one address (the sockaddr is what the code reads)."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr: tuple[Any, ...] = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def test_asset_bytes_reads_file_url_in_tempdir() -> None:
    data = _png_bytes(1)
    fd, name = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    p = Path(name)
    p.write_bytes(data)
    try:
        assert _asset_bytes(f"file://{quote(str(p))}") == data
    finally:
        p.unlink(missing_ok=True)


def test_asset_bytes_rejects_file_outside_tempdir() -> None:
    with pytest.raises(ValueError, match="outside the temp dir"):
        _asset_bytes("file:///etc/hosts")


def test_asset_bytes_rejects_non_https_scheme() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _asset_bytes("ftp://example.com/x.png")


def test_asset_bytes_rejects_internal_host() -> None:
    with pytest.raises(ValueError, match="internal address|cannot resolve"):
        _asset_bytes("https://127.0.0.1/x.png")


# --- SSRF: resolve once, validate every address, pin to a validated IP ---


def test_validated_addresses_returns_public_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [_gai_record("93.184.216.34", 443)])
    assert _validated_addresses("asset.example", 443) == ["93.184.216.34"]


def test_validated_addresses_rejects_multi_record_with_one_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A round-robin / multi-record answer where ANY address is internal is rejected wholesale,
    # so an attacker cannot smuggle a private record alongside a public one.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [_gai_record("93.184.216.34", 443), _gai_record("10.0.0.5", 443)],
    )
    with pytest.raises(AssetFetchError, match="internal address 10.0.0.5"):
        _validated_addresses("asset.example", 443)


def test_validated_addresses_normalizes_ipv4_mapped_ipv6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ::ffff:127.0.0.1 is loopback once de-mapped; the guard must see through the IPv4-mapped form.
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [_gai_record("::ffff:127.0.0.1", 443)]
    )
    with pytest.raises(AssetFetchError, match="internal address 127.0.0.1"):
        _validated_addresses("asset.example", 443)


def test_validated_addresses_rejects_unspecified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [_gai_record("0.0.0.0", 443)])
    with pytest.raises(AssetFetchError, match="internal address 0.0.0.0"):
        _validated_addresses("asset.example", 443)


def test_validated_addresses_rejects_unresolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: Any, **k: Any) -> list[Any]:
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(AssetFetchError, match="cannot resolve"):
        _validated_addresses("asset.example", 443)


class _FakeStream:
    """Stand-in for httpx's streaming response context manager."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self) -> Iterator[bytes]:
        yield self._data


def test_asset_bytes_pins_to_resolved_ip_and_resists_rebind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate DNS rebinding: the first resolution returns a public IP, a second would return a
    # private one. With a real pin the host is resolved exactly once and the connection is made to
    # that validated IP literal, so the second (malicious) answer is never consulted.
    calls = {"n": 0}

    def fake_gai(host: str, port: int, *a: Any, **k: Any) -> list[Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [_gai_record("93.184.216.34", port)]
        return [_gai_record("10.0.0.5", port)]  # the rebind target, must never be used

    monkeypatch.setattr(socket, "getaddrinfo", fake_gai)

    captured: dict[str, Any] = {}

    def fake_stream(
        self: httpx.Client,
        method: str,
        url: httpx.URL,
        *,
        headers: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
        **kw: Any,
    ) -> _FakeStream:
        captured["url"] = url
        captured["headers"] = headers
        captured["extensions"] = extensions
        return _FakeStream(b"PINNED-BYTES")

    monkeypatch.setattr(httpx.Client, "stream", fake_stream)

    data = _asset_bytes("https://asset.example/x.png")

    assert data == b"PINNED-BYTES"
    assert calls["n"] == 1  # resolved once; the rebind answer was never requested
    assert captured["url"].host == "93.184.216.34"  # connected to the validated IP, not the name
    assert captured["headers"]["Host"] == "asset.example"  # original Host preserved (vhost routing)
    assert captured["extensions"]["sni_hostname"] == "asset.example"  # SNI/cert hostname preserved


def test_asset_bytes_enforces_size_cap_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [_gai_record("93.184.216.34", 443)])

    def fake_stream(self: httpx.Client, method: str, url: httpx.URL, **kw: Any) -> _FakeStream:
        return _FakeStream(b"x" * (50 * 1024 * 1024 + 1))

    monkeypatch.setattr(httpx.Client, "stream", fake_stream)
    with pytest.raises(AssetFetchError, match="size cap"):
        _asset_bytes("https://asset.example/big.png")


# --- narrowed cross-provider fallback ---


def test_fallback_exception_types_cover_provider_and_asset_errors() -> None:
    types = _fallback_exception_types()
    assert AssetFetchError in types
    assert httpx.HTTPError in types
    # every entry is a real exception type (never a bare placeholder)
    assert all(isinstance(t, type) and issubclass(t, BaseException) for t in types)


def test_generate_uses_gmi_when_it_succeeds() -> None:
    gen = GenblazeGenerator("gmi-key", gmi_model="seedream", openai_api_key="oai-key")
    sentinel = _result("seedream", "gmicloud-image")
    gen._generate_gmi = lambda prompt: sentinel  # type: ignore[method-assign]

    def _should_not_call(prompt: str) -> GenerationResult:
        raise AssertionError("OpenAI must not be called when GMICloud succeeds")

    gen._generate_openai = _should_not_call  # type: ignore[method-assign]
    assert gen.generate("a fox") is sentinel


def test_generate_falls_back_to_openai_on_network_error() -> None:
    gen = GenblazeGenerator("gmi-key", gmi_model="seedream", openai_api_key="oai-key")
    sentinel = _result("gpt-image-1", "openai-dalle")

    def _boom(prompt: str) -> GenerationResult:
        raise httpx.ConnectError("GMICloud unreachable")

    gen._generate_gmi = _boom  # type: ignore[method-assign]
    gen._generate_openai = lambda prompt: sentinel  # type: ignore[method-assign]
    assert gen.generate("a fox") is sentinel


def test_generate_falls_back_to_openai_on_asset_fetch_error() -> None:
    gen = GenblazeGenerator("gmi-key", gmi_model="seedream", openai_api_key="oai-key")
    sentinel = _result("gpt-image-1", "openai-dalle")

    def _boom(prompt: str) -> GenerationResult:
        raise AssetFetchError("refusing to fetch a genblaze asset from internal address 10.0.0.1")

    gen._generate_gmi = _boom  # type: ignore[method-assign]
    gen._generate_openai = lambda prompt: sentinel  # type: ignore[method-assign]
    assert gen.generate("a fox") is sentinel


def test_generate_reraises_network_error_when_no_openai_key() -> None:
    gen = GenblazeGenerator("gmi-key", gmi_model="seedream", openai_api_key=None)

    def _boom(prompt: str) -> GenerationResult:
        raise httpx.ConnectError("GMICloud unreachable")

    gen._generate_gmi = _boom  # type: ignore[method-assign]
    with pytest.raises(httpx.ConnectError, match="GMICloud unreachable"):
        gen.generate("a fox")


def test_generate_propagates_unexpected_error_without_falling_back() -> None:
    # A programming error (TypeError, attribute change, decode failure) must NOT be masked as a
    # provider failure or trigger a silent provider switch, even when an OpenAI key is present.
    gen = GenblazeGenerator("gmi-key", gmi_model="seedream", openai_api_key="oai-key")

    def _boom(prompt: str) -> GenerationResult:
        raise TypeError("genblaze result shape changed")

    def _should_not_call(prompt: str) -> GenerationResult:
        raise AssertionError("OpenAI must not be called on an unexpected (non-provider) error")

    gen._generate_gmi = _boom  # type: ignore[method-assign]
    gen._generate_openai = _should_not_call  # type: ignore[method-assign]
    with pytest.raises(TypeError, match="result shape changed"):
        gen.generate("a fox")
