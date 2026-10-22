"""GET /demo/remark-failover: a real watermark-REMOVAL attack does not defeat recovery.

The combinatorial verdict cases mock at the decode/match seam (a FakeWatermarker for the watermark
decode, the resolver for the fingerprint match) so they run without torch. One integration test uses
the REAL TrustMark variant P: it stages the real removal attack and confirms the real decoder is
defeated while the real PDQ fingerprint still recovers the manifest. It is skipped when the
`watermark` extra is absent, the same way the other real-TrustMark tests are.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from veridex_api import demo, sbr
from veridex_api.demo import DEMO_MANIFEST_ID, DEMO_WATERMARK_ID, seed_demo
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.models import SoftBindingQueryResult
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker

try:
    # An actual import (not find_spec): a pruned extra can leave an empty `trustmark` namespace dir
    # so find_spec lies; importing the symbol confirms torch and the model deps are present too.
    from trustmark import TrustMark  # noqa: F401

    _HAS_TRUSTMARK = True
except ImportError:
    _HAS_TRUSTMARK = False

real_only = pytest.mark.skipif(
    not _HAS_TRUSTMARK, reason="needs the `watermark` extra (trustmark + torch)"
)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def seeded() -> Iterator[Resolver]:
    """A resolver with the demo asset registered (the live default: PDQ path via FakeWatermarker),
    wired into the app. The staged-bytes cache is reset around each test so a swapped watermarker
    never reads a stale stage."""
    resolver = Resolver(InMemoryIndex(), FakeWatermarker())
    log = TransparencyLog()
    seed_demo(resolver, log)
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    demo.reset_remark_cache()
    yield resolver
    sbr.set_resolver(None)
    sbr.set_log(None)
    demo.reset_remark_cache()


async def _get_failover() -> dict[str, Any]:
    async with _client() as c:
        r = await c.get("/demo/remark-failover")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


# --- combinatorial verdict cases (mocked at the decode/match seam, no torch) ---------------------


async def test_watermark_removed_fingerprint_survives(
    seeded: Resolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The interesting case: the removal attack destroyed the watermark (decode returns no id) but
    # the perceptual fingerprint still recovers the manifest.
    monkeypatch.setattr(demo, "_load_remark_watermarker", lambda: FakeWatermarker(decoded_id=None))
    body = await _get_failover()

    assert body["available"] is True
    assert body["staged"] is True
    assert "staged" in body["stagedNote"].lower()
    assert body["attack"]["parameters"]["gaussianBlurRadius"] == demo.REMARK_BLUR_RADIUS
    assert body["attack"]["parameters"]["jpegQuality"] == demo.REMARK_JPEG_QUALITY
    assert "remark" in body["attack"]["note"].lower()

    assert body["watermark"] == {
        "attempted": True,
        "recovered": False,
        "decodedId": None,
        "expectedId": DEMO_WATERMARK_ID,
        "note": None,
    }
    fp = body["fingerprint"]
    assert fp["attempted"] is True
    assert fp["recovered"] is True
    assert fp["matchedManifestId"] == DEMO_MANIFEST_ID
    assert fp["threshold"] == 31
    assert 0 <= fp["hammingDistance"] <= 31
    assert "survives watermark removal" in body["verdict"]


async def test_both_soft_bindings_survive(
    seeded: Resolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A weaker transform leaves the watermark intact: the fake decodes the expected id, and the
    # fingerprint also matches, so the verdict says the failover was not exercised.
    monkeypatch.setattr(
        demo, "_load_remark_watermarker", lambda: FakeWatermarker(decoded_id=DEMO_WATERMARK_ID)
    )
    body = await _get_failover()

    assert body["available"] is True
    assert body["watermark"]["recovered"] is True
    assert body["watermark"]["decodedId"] == DEMO_WATERMARK_ID
    assert body["fingerprint"]["recovered"] is True
    assert "did not defeat the watermark" in body["verdict"]


async def test_both_soft_bindings_fail(seeded: Resolver, monkeypatch: pytest.MonkeyPatch) -> None:
    # Watermark destroyed AND the fingerprint does not match (the resolver returns no match): the
    # honest verdict is that the attack defeated both. The demo asset stays registered, so this is a
    # real verdict, not the empty-registry degrade.
    monkeypatch.setattr(demo, "_load_remark_watermarker", lambda: FakeWatermarker(decoded_id=None))
    monkeypatch.setattr(
        seeded, "resolve_by_content", lambda img: SoftBindingQueryResult(matches=[])
    )
    body = await _get_failover()

    assert body["available"] is True
    assert body["watermark"]["recovered"] is False
    assert body["fingerprint"]["recovered"] is False
    assert body["fingerprint"]["matchedManifestId"] is None
    # the raw PDQ distance is still reported on a failure (the honesty of the surface)
    assert isinstance(body["fingerprint"]["hammingDistance"], int)
    assert "defeated both soft bindings" in body["verdict"]


async def test_watermark_survives_fingerprint_fails(
    seeded: Resolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        demo, "_load_remark_watermarker", lambda: FakeWatermarker(decoded_id=DEMO_WATERMARK_ID)
    )
    monkeypatch.setattr(
        seeded, "resolve_by_content", lambda img: SoftBindingQueryResult(matches=[])
    )
    body = await _get_failover()

    assert body["watermark"]["recovered"] is True
    assert body["fingerprint"]["recovered"] is False
    assert "watermark survived but the perceptual fingerprint did not" in body["verdict"]


# --- honest degrade cases ------------------------------------------------------------------------


async def test_partial_live_when_trustmark_unavailable(
    seeded: Resolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The lean deploy (no TrustMark model): the fingerprint half still runs LIVE on the attacked
    # bytes, and the watermark half honestly reports attempted=false with a pointer to the
    # real-model integration test instead of faking a decode.
    monkeypatch.setattr(demo, "_load_remark_watermarker", lambda: None)
    body = await _get_failover()

    assert body["available"] is True
    assert body["staged"] is True
    assert "not run here" in body["stagedNote"] or "watermark half" in body["stagedNote"]
    assert body["attack"]["parameters"]["gaussianBlurRadius"] == demo.REMARK_BLUR_RADIUS

    wm = body["watermark"]
    assert wm["attempted"] is False
    assert wm["recovered"] is False
    assert wm["decodedId"] is None
    assert "integration test" in wm["note"]

    fp = body["fingerprint"]
    assert fp["attempted"] is True
    assert fp["recovered"] is True  # real PDQ recovery, computed live on the attacked bytes
    assert fp["matchedManifestId"] == DEMO_MANIFEST_ID
    assert 0 <= fp["hammingDistance"] <= 31
    assert "computed live" in body["verdict"]
    assert "not deployed" in body["verdict"]


async def test_degrades_on_empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    # A resolver with no demo manifest registered: available=false with an honest reason, not a 500.
    resolver = Resolver(InMemoryIndex(), FakeWatermarker())
    sbr.set_resolver(resolver)
    sbr.set_log(TransparencyLog())
    demo.reset_remark_cache()
    monkeypatch.setattr(
        demo, "_load_remark_watermarker", lambda: FakeWatermarker(decoded_id=DEMO_WATERMARK_ID)
    )
    try:
        body = await _get_failover()
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)
        demo.reset_remark_cache()

    assert body["available"] is False
    assert "not registered" in body["reason"]


# --- the real end-to-end experiment (skipped without the `watermark` extra) ----------------------


@real_only
async def test_real_removal_attack_defeats_trustmark_but_fingerprint_survives(
    seeded: Resolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing empirical claim on real primitives: the real removal attack empirically
    defeats the REAL TrustMark P decoder (the decoded id is not the embedded id), while the REAL PDQ
    fingerprint still recovers the manifest within threshold. Nothing is asserted about the failure;
    it is read from a live decode of the attacked bytes."""
    from veridex_provenance.watermark import TrustMarkWatermarker

    real = TrustMarkWatermarker()
    monkeypatch.setattr(demo, "_load_remark_watermarker", lambda: real)
    body = await _get_failover()

    assert body["available"] is True
    # the real decoder is defeated by the removal attack
    assert body["watermark"]["recovered"] is False
    assert body["watermark"]["decodedId"] != DEMO_WATERMARK_ID
    # the real perceptual fingerprint still recovers the manifest within threshold
    fp = body["fingerprint"]
    assert fp["recovered"] is True
    assert fp["matchedManifestId"] == DEMO_MANIFEST_ID
    assert 0 < fp["hammingDistance"] <= 31
    assert "survives watermark removal" in body["verdict"]
