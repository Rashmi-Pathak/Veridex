"""Tests for the live, rate-limited generation endpoint (the judge-driven loop).

Network-free: a FakeGenerator stands in for Genblaze, the resolver/log are in-memory, and storage is
off. The headline assertion is that a freshly generated asset, once stripped (re-encoded), recovers
to its own manifest through /matches/byContent: the live loop closes. The rest pin the cost guard:
every exhaustion or failure path serves the seeded asset (the loop always closes), a failed attempt
still consumes the global budget (the ceiling counts attempts, never refunds), the body-size cap,
and prompt validation.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Iterator
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from veridex_api import demo, generate, sbr
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker
from veridex_worker.generator import AssetFetchError, FakeGenerator


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Credential-free, network-free: in-memory resolver/log, a fake generator, generation enabled.
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(TransparencyLog())
    sbr.set_storage(None)
    monkeypatch.setenv("VERIDEX_LIVE_GENERATE", "1")
    monkeypatch.delenv("GMI_CLOUD_API_KEY", raising=False)
    generate.reset_limiter()
    generate.set_generator(FakeGenerator())
    # Seed the demo asset so the fallback paths return a registered, recoverable asset.
    demo.seed_demo(sbr.get_resolver(), sbr.get_log(), None)
    with TestClient(app) as c:
        yield c
    sbr.set_resolver(None)
    sbr.set_log(None)
    sbr.set_storage(None)
    generate.set_generator(None)
    generate.reset_limiter()


def _gen(
    client: TestClient, prompt: str = "a single rooted oak tree", ip: str = "1.2.3.4"
) -> Response:
    return cast(
        Response,
        client.post("/demo/generate", json={"prompt": prompt}, headers={"x-forwarded-for": ip}),
    )


def test_generate_then_strip_recovers_to_its_own_manifest(client: TestClient) -> None:
    r = _gen(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fellBackToSeed"] is False
    assert body["manifestId"].startswith("urn:c2pa:")
    assert body["image"].startswith("data:image/jpeg;base64,")
    assert body["model"] == "fake-image-1"
    assert body["manifest"]["systemProvenance"]["generator"] == "genblaze"
    assert body["merkleIndex"] >= 0
    # The redaction layer withholds the prompt from the returned manifest.
    assert "prompt" not in body["manifest"].get("personalProvenance", {})

    # Strip: decode the returned image and re-encode it (destroys any embedded credential), then
    # recover it through the public content route. It must resolve to the manifest just minted.
    raw = base64.b64decode(body["image"].split(",", 1)[1])
    stripped = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGB").save(stripped, "JPEG", quality=85)
    rec = client.post(
        "/matches/byContent",
        files={"file": ("stripped.jpg", stripped.getvalue(), "image/jpeg")},
    )
    assert rec.status_code == 200, rec.text
    matches = rec.json()["matches"]
    assert matches and matches[0]["manifestId"] == body["manifestId"]


def test_per_ip_cap_serves_the_seed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIDEX_GEN_PER_IP_DAY", "2")
    monkeypatch.setenv("VERIDEX_GEN_GLOBAL_DAY", "100")
    generate.reset_limiter()
    assert _gen(client, ip="9.9.9.9").json()["fellBackToSeed"] is False
    assert _gen(client, ip="9.9.9.9").json()["fellBackToSeed"] is False
    capped = _gen(client, ip="9.9.9.9")
    assert capped.status_code == 200
    assert capped.json()["fellBackToSeed"] is True
    assert "visitor" in (capped.json()["reason"] or "")
    # A different visitor still gets a real generation (the cap is per-IP).
    assert _gen(client, ip="8.8.8.8").json()["fellBackToSeed"] is False


def test_global_cap_serves_the_seed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIDEX_GEN_PER_IP_DAY", "100")
    monkeypatch.setenv("VERIDEX_GEN_GLOBAL_DAY", "1")
    generate.reset_limiter()
    assert _gen(client, ip="1.1.1.1").json()["fellBackToSeed"] is False
    capped = _gen(client, ip="2.2.2.2")
    assert capped.status_code == 200
    assert capped.json()["fellBackToSeed"] is True
    assert "budget" in (capped.json()["reason"] or "")


def test_failed_attempt_still_consumes_the_global_budget(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cost ceiling counts ATTEMPTS, never refunds: a provider failure (which may have billed)
    # must still consume the global slot, so a flaky provider cannot defeat the daily ceiling.
    class _Boom:
        def generate(self, prompt: str) -> object:
            raise AssetFetchError("provider down")

    monkeypatch.setenv("VERIDEX_GEN_PER_IP_DAY", "100")
    monkeypatch.setenv("VERIDEX_GEN_GLOBAL_DAY", "1")
    generate.reset_limiter()
    generate.set_generator(_Boom())
    first = _gen(client, ip="1.1.1.1")
    assert first.status_code == 200
    assert first.json()["fellBackToSeed"] is True
    # The failed attempt consumed the global budget of 1, so a fresh, working generator now also
    # gets the seed (the ceiling held despite the failure).
    generate.set_generator(FakeGenerator())
    second = _gen(client, ip="2.2.2.2")
    assert second.status_code == 200
    assert second.json()["fellBackToSeed"] is True


def test_disabled_serves_the_seed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIDEX_LIVE_GENERATE", "0")
    r = _gen(client)
    assert r.status_code == 200
    body = r.json()
    assert body["fellBackToSeed"] is True
    assert body["manifestId"] == demo.DEMO_MANIFEST_ID
    assert "not enabled" in (body["reason"] or "")


def test_seed_response_withholds_prompt_and_self_verifies(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fallback seed response returns the primary asset, whose prompt sits in system_provenance.
    # The disclosure must withhold it, AND the returned signature must verify against the returned
    # (redacted) manifest, so the response is internally consistent (no signature/payload mismatch).
    monkeypatch.setenv("VERIDEX_LIVE_GENERATE", "0")
    body = _gen(client).json()
    assert body["fellBackToSeed"] is True
    assert "prompt" not in body["manifest"]["systemProvenance"]
    assert "prompt" not in body["manifest"].get("personalProvenance", {})
    v = client.post(
        "/verify",
        json={"manifest": body["manifest"], "signatureB64": body["signatureB64"]},
    )
    assert v.status_code == 200
    assert v.json()["signatureValid"] is True


def test_provider_error_serves_the_seed(client: TestClient) -> None:
    class _Boom:
        def generate(self, prompt: str) -> object:
            raise AssetFetchError("provider down")

    generate.set_generator(_Boom())
    r = _gen(client, ip="7.7.7.7")
    assert r.status_code == 200
    body = r.json()
    assert body["fellBackToSeed"] is True
    assert body["manifestId"] == demo.DEMO_MANIFEST_ID


def test_oversized_body_is_rejected(client: TestClient) -> None:
    big = b'{"prompt": "' + b"x" * (_body_over_cap()) + b'"}'
    r = client.post("/demo/generate", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413


def _body_over_cap() -> int:
    return generate._MAX_BODY_BYTES + 1


def test_prompt_validation(client: TestClient) -> None:
    assert client.post("/demo/generate", json={"prompt": "   "}).status_code == 400
    assert (
        client.post("/demo/generate", json={"prompt": "x" * (generate._PROMPT_MAX + 1)}).status_code
        == 400
    )
    assert client.post("/demo/generate", json={"prompt": 123}).status_code == 400
    assert client.post("/demo/generate", json={}).status_code == 400
