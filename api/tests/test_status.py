"""Tests for the live /status judges surface.

Network-free: in-memory resolver/log, the demo seeded. Asserts the status aggregates the real,
measured state (the transparency tree, the storage backend, the advertised algorithms, the
generation config) and that the live recovery self-test actually recovers the seeded asset.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from veridex_api import demo, generate, sbr, status
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(TransparencyLog())
    sbr.set_storage(None)
    monkeypatch.delenv("VERIDEX_LIVE_GENERATE", raising=False)
    monkeypatch.delenv("GMI_CLOUD_API_KEY", raising=False)
    generate.reset_limiter()
    generate.set_generator(None)
    status.reset_status_cache()
    demo.seed_demo(sbr.get_resolver(), sbr.get_log(), None)
    with TestClient(app) as c:
        yield c
    sbr.set_resolver(None)
    sbr.set_audio_resolver(None)
    sbr.set_video_resolver(None)
    sbr.set_log(None)
    sbr.set_storage(None)
    generate.set_generator(None)
    generate.reset_limiter()


def _status(client: TestClient) -> Response:
    return cast(Response, client.get("/status"))


def test_status_reports_real_measured_state(client: TestClient) -> None:
    r = _status(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service"] == "veridex-api"
    # The transparency tree reflects the seeded leaves (the demo seeds DEMO_ENTRY_COUNT of them).
    assert body["transparency"]["treeSize"] == demo.DEMO_ENTRY_COUNT
    assert body["transparency"]["checkpointEpoch"] == demo.DEMO_ENTRY_COUNT
    assert len(body["transparency"]["rootHash"]) == 64
    assert body["transparency"]["keySource"] in {"configured", "ephemeral"}
    # The advertised algorithms are honest: the registered watermark, no fingerprint (PDQ internal).
    assert "com.adobe.trustmark.P" in body["algorithms"]["watermarks"]
    assert body["algorithms"]["fingerprints"] == []
    # Storage is off in this fixture; the recovery index is the in-memory scaffold.
    assert body["storage"]["backend"] == "none"
    assert body["recoveryIndex"] == "in-memory"


def test_status_generation_config_reflects_disabled(client: TestClient) -> None:
    body = _status(client).json()
    assert body["generation"]["enabled"] is False
    assert body["generation"]["configured"] is False
    assert body["generation"]["perIpPerDay"] >= 1
    assert body["generation"]["globalPerDay"] >= 1


def test_status_recovery_self_test_recovers_the_seed(client: TestClient) -> None:
    body = _status(client).json()
    st = body["recoverySelfTest"]
    assert st["recovered"] is True
    assert st["manifestId"] == demo.DEMO_MANIFEST_ID
    assert st["similarityScore"] == 100
    assert st["latencyMs"] >= 0


def test_storage_probe_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # A real B2 outage/auth error during the status storage probe must be logged (visible in the
    # Render logs), not silently surfaced as a benign demoAssetPresent=false on the judges page.
    from veridex_storage.storage import InMemoryStorage

    storage = InMemoryStorage()

    def _boom(_key: str) -> bool:
        raise RuntimeError("b2 down")

    monkeypatch.setattr(storage, "exists", _boom)
    sbr.set_storage(storage)
    try:
        with caplog.at_level("WARNING"):
            result = status._storage_status()
        assert result.demo_asset_present is False
        assert any("storage probe failed" in r.message for r in caplog.records)
    finally:
        sbr.set_storage(None)
