"""Tests for the multi-provider provenance demos (/demo/providers, /demo/provider/{slug}).

Proves Rooted recovers provenance for real AI media from several distinct generators (Nano Banana,
Flux, Qwen): each provider asset is seeded and recovers to its own manifest, and the recovered
manifest discloses the real model + provider while withholding the prompt (the SB 942 redaction).
Network-free: in-memory resolver/log, the providers seeded.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from veridex_api import demo, sbr
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker


@pytest.fixture
def client() -> Iterator[TestClient]:
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(TransparencyLog())
    sbr.set_storage(None)
    demo.seed_providers(sbr.get_resolver(), sbr.get_log(), None)
    with TestClient(app) as c:
        yield c
    sbr.set_resolver(None)
    sbr.set_log(None)
    sbr.set_storage(None)


def _providers(client: TestClient) -> list[dict[str, Any]]:
    r = client.get("/demo/providers")
    assert r.status_code == 200, r.text
    return cast(list[dict[str, Any]], r.json())


def test_providers_list_names_the_real_models(client: TestClient) -> None:
    provs = _providers(client)
    models = {p["model"] for p in provs}
    assert {"nano-banana-2", "flux-2/pro-text-to-image", "qwen/text-to-image"} <= models
    # Every provider carries the honest kie.ai provider attribution.
    assert all(p["provider"].startswith("kie.ai-") for p in provs)


def test_provider_image_served_and_unknown_is_404(client: TestClient) -> None:
    provs = _providers(client)
    for p in provs:
        img = client.get(f"/demo/provider/{p['slug']}")
        assert img.status_code == 200, p["slug"]
        assert img.headers["content-type"] == "image/jpeg"
        assert len(img.content) > 0
    assert client.get("/demo/provider/nope").status_code == 404


def test_each_provider_asset_recovers_to_its_manifest(client: TestClient) -> None:
    for p in _providers(client):
        img = client.get(f"/demo/provider/{p['slug']}").content
        r = client.post("/matches/byContent", files={"file": ("x.jpg", img, "image/jpeg")})
        assert r.status_code == 200, r.text
        matches = r.json().get("matches") or []
        assert matches, f"no recovery for {p['slug']}"
        assert matches[0]["manifestId"] == p["manifestId"]
        assert matches[0]["similarityScore"] == 100


def test_recovered_manifest_discloses_model_but_withholds_prompt(client: TestClient) -> None:
    p = _providers(client)[0]
    m = client.get(f"/manifests/{p['manifestId']}").json()
    sysprov = m["systemProvenance"]
    assert sysprov["model"] == p["model"]
    assert sysprov["provider"] == p["provider"]
    # The redaction layer withholds the prompt: it is shown as demo metadata in the list, never in
    # the recovered manifest's provenance.
    assert "prompt" not in sysprov
    assert m.get("personalProvenance", {}) == {}
