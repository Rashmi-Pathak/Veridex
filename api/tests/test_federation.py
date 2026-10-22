"""Federated SBR: on a local miss, forward the {alg, value} soft-binding query to peer resolvers and
return the first peer's recovered manifest, labeled with the recovering peer. The forward target is
an operator allowlist (VERIDEX_SBR_PEERS), never request-supplied, and is SSRF-guarded in production.
Network-free: the peer HTTP client is a MockTransport injected via the _peer_client seam, so the
global httpx (which the app's own clients use) is never patched."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
import numpy as np
import pytest
from httpx import ASGITransport
from PIL import Image

from veridex_api import sbr
from veridex_api.main import app
from veridex_provenance.models import ALG_TRUSTMARK_P, Manifest, SoftBinding
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _mock_peer_client(payload: Mapping[str, object]) -> httpx.AsyncClient:
    """An httpx client whose every request returns a fixed SBR result (scoped to the forward)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _raise_if_called() -> httpx.AsyncClient:
    raise AssertionError("a local hit must not forward to a peer")


@pytest.fixture
def reset_resolver() -> object:
    yield
    sbr.set_resolver(None)


def _empty_resolver() -> Resolver:
    return Resolver(InMemoryIndex(), FakeWatermarker())


def test_peer_urls_parses_strips_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("VERIDEX_SBR_PEERS", "https://a.example, https://b.example ,")
    assert sbr._peer_urls() == ["https://a.example", "https://b.example"]


def test_peer_guard_rejects_unsafe_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    assert sbr._peer_is_safe("https://peer.example") is True
    assert sbr._peer_is_safe("http://peer.example") is False  # http rejected in prod
    assert sbr._peer_is_safe("https://localhost") is False  # loopback host
    assert sbr._peer_is_safe("https://127.0.0.1") is False  # loopback IP
    assert sbr._peer_is_safe("https://10.0.0.5") is False  # private IP
    assert sbr._peer_is_safe("https://169.254.1.1") is False  # link-local IP
    assert sbr._peer_is_safe("ftp://peer.example") is False  # bad scheme


def test_peer_guard_allows_http_loopback_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    assert sbr._peer_is_safe("http://localhost:8001") is True


async def test_federated_returns_local_hit_without_forwarding(
    reset_resolver: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("VERIDEX_SBR_PEERS", "https://peer.example")
    resolver = _empty_resolver()
    manifest = Manifest(
        manifest_id="urn:c2pa:local-1",
        asset_sha256="ab" * 32,
        created_at="t",
        system_provenance={},
        soft_bindings=[SoftBinding(alg=ALG_TRUSTMARK_P, value="LOCAL1")],
    )
    resolver.register(manifest, Image.fromarray(np.zeros((64, 64, 3), dtype=np.uint8)), "LOCAL1")
    sbr.set_resolver(resolver)
    monkeypatch.setattr(sbr, "_peer_client", _raise_if_called)  # a forward would fail the test
    async with _client() as c:
        body = (
            await c.get(
                "/matches/byBinding/federated", params={"alg": ALG_TRUSTMARK_P, "value": "LOCAL1"}
            )
        ).json()
    assert body["matches"][0]["manifestId"] == "urn:c2pa:local-1"
    assert body["matches"][0]["endpoint"] is None  # local hit is not labeled with a peer


async def test_federated_forwards_on_local_miss_and_labels_the_peer(
    reset_resolver: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("VERIDEX_SBR_PEERS", "https://peer.example")
    sbr.set_resolver(_empty_resolver())  # local always misses
    payload = {"matches": [{"manifestId": "urn:c2pa:peer-1", "similarityScore": None}]}
    monkeypatch.setattr(sbr, "_peer_client", lambda: _mock_peer_client(payload))
    async with _client() as c:
        body = (
            await c.get(
                "/matches/byBinding/federated", params={"alg": ALG_TRUSTMARK_P, "value": "PEERONLY"}
            )
        ).json()
    assert body["matches"][0]["manifestId"] == "urn:c2pa:peer-1"
    assert body["matches"][0]["endpoint"] == "https://peer.example"  # labeled with the peer


async def test_federated_miss_with_no_peers_is_empty(
    reset_resolver: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VERIDEX_SBR_PEERS", raising=False)
    sbr.set_resolver(_empty_resolver())
    async with _client() as c:
        body = (
            await c.get(
                "/matches/byBinding/federated", params={"alg": ALG_TRUSTMARK_P, "value": "NONE"}
            )
        ).json()
    assert body["matches"] == []


async def test_demo_federation_and_supported_algorithms_advertise_peers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("VERIDEX_SBR_PEERS", "https://peer.example")
    async with _client() as c:
        fed = (await c.get("/demo/federation")).json()
        algs = (await c.get("/services/supportedAlgorithms")).json()
    assert fed["enabled"] is True
    assert fed["peers"] == ["https://peer.example"]
    assert algs["peers"] == ["https://peer.example"]
