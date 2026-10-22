"""Demo seed: register one real signed fixture asset so the recovery loop closes to VERIFIED
without any external credentials, and serve its exact bytes so the front end can recover it."""

from __future__ import annotations

import io

import httpx
from httpx import ASGITransport
from PIL import Image

from veridex_api import sbr
from veridex_api.demo import (
    DEMO_ENTRY_COUNT,
    DEMO_MANIFEST_ID,
    demo_sample_bytes,
    seed_demo,
    speech_demo_bytes,
)
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker
from veridex_storage.storage import InMemoryStorage


def _fresh() -> tuple[Resolver, TransparencyLog]:
    return Resolver(InMemoryIndex(), FakeWatermarker()), TransparencyLog()


def test_seed_registers_a_recoverable_asset() -> None:
    resolver, log = _fresh()
    seed_demo(resolver, log)
    img = Image.open(io.BytesIO(demo_sample_bytes()))
    result = resolver.resolve_by_content(img)
    assert [m.manifest_id for m in result.matches] == [DEMO_MANIFEST_ID]


def test_seed_is_idempotent() -> None:
    resolver, log = _fresh()
    seed_demo(resolver, log)
    seed_demo(
        resolver, log
    )  # a second call (e.g. a restart against a persistent backend) is a no-op
    result = resolver.resolve_by_content(Image.open(io.BytesIO(demo_sample_bytes())))
    assert len(result.matches) == 1
    assert log.size == DEMO_ENTRY_COUNT  # seeded once, not twice


def test_primary_asset_has_real_genblaze_provenance() -> None:
    # The primary demo asset is a real image generated via Genblaze on GMI Cloud (not a fixture),
    # so its system provenance names the real model and provider, honestly.
    resolver, log = _fresh()
    seed_demo(resolver, log)
    manifest = resolver.get_manifest(DEMO_MANIFEST_ID)
    assert manifest is not None
    assert manifest.system_provenance["model"] == "seedream-5.0-lite"
    assert manifest.system_provenance["provider"] == "gmicloud-image"


def test_seed_populates_the_log() -> None:
    resolver, log = _fresh()
    seed_demo(resolver, log)
    entries = log.entries()
    assert len(entries) == DEMO_ENTRY_COUNT
    assert entries[0] == (0, DEMO_MANIFEST_ID, entries[0][2])  # primary is the first leaf


async def test_transparency_log_route() -> None:
    resolver, log = _fresh()
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    seed_demo(resolver, log)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/transparency/log")
            assert r.status_code == 200
            body = r.json()
            assert body["treeSize"] == DEMO_ENTRY_COUNT
            assert len(body["entries"]) == DEMO_ENTRY_COUNT
            assert body["entries"][0]["manifestId"] == DEMO_MANIFEST_ID
            assert len(body["rootHash"]) == 64  # sha256 hex
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)


async def test_log_and_proof_leaf_index_agree() -> None:
    # /transparency/log and /transparency/proof must report the SAME leaf index for a manifest
    # (both 0-based), so a client can cross-reference a log entry against its inclusion proof.
    resolver, log = _fresh()
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    seed_demo(resolver, log)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            log_r = await c.get("/transparency/log")
            proof_r = await c.get(f"/transparency/proof/{DEMO_MANIFEST_ID}")
            assert proof_r.status_code == 200
            log_idx = log_r.json()["entries"][0]["leafIndex"]
            proof_idx = proof_r.json()["leafIndex"]
            assert log_idx == proof_idx == 0
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)


async def test_demo_speech_route_serves_the_clip() -> None:
    # The speech asset is the input Genblaze's AssemblyAI STT connector transcribes. It must be
    # served over public https as audio so the connector (and the UI) can fetch it.
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/demo/speech")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == speech_demo_bytes()
    assert len(r.content) > 1000  # a real clip, not an empty body


async def test_demo_sample_route_then_recover() -> None:
    resolver, log = _fresh()
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    seed_demo(resolver, log)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            sample = await c.get("/demo/sample")
            assert sample.status_code == 200
            assert sample.headers["content-type"].startswith("image/")

            rec = await c.post(
                "/matches/byContent",
                files={"file": ("sample.jpg", sample.content, "image/jpeg")},
            )
            assert rec.status_code == 200
            assert rec.json()["matches"][0]["manifestId"] == DEMO_MANIFEST_ID
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)


async def test_demo_robustness_grid_is_honest() -> None:
    # The grid applies real transforms to the demo asset and runs the real recovery path on each.
    # PDQ survives re-encode and scaling but not rotation, so the grid must show honest pass/fail.
    resolver, log = _fresh()
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    seed_demo(resolver, log)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            body = (await c.get("/demo/robustness")).json()
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)

    assert body["manifestId"] == DEMO_MANIFEST_ID
    assert body["threshold"] == 31
    rows = {r["transform"]: r for r in body["rows"]}
    # the original self-recovers at distance 0
    assert rows["original"]["recovered"] is True
    assert rows["original"]["hammingDistance"] == 0
    # PDQ is robust to re-encode and scaling
    assert rows["JPEG quality 50"]["recovered"] is True
    assert rows["downscale 50%"]["recovered"] is True
    assert rows["screenshot (downscale + JPEG)"]["recovered"] is True
    # PDQ is NOT rotation-invariant: an honest fail at a large distance
    assert rows["rotate 90 deg"]["recovered"] is False
    assert rows["rotate 90 deg"]["hammingDistance"] > 31
    # every row reports a raw Hamming distance, even the failures (the honesty of the grid)
    assert all(isinstance(r["hammingDistance"], int) for r in body["rows"])


async def test_demo_rebuild_reconstructs_the_index_from_storage() -> None:
    # B2 is the source of truth: with the live index thrown away, the recovery index and the demo
    # recovery must reconstruct from the stored manifests/assets alone.
    resolver, log = _fresh()
    storage = InMemoryStorage()
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    sbr.set_storage(storage)
    seed_demo(resolver, log, storage)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            body = (await c.get("/demo/rebuild")).json()
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)
        sbr.set_storage(None)

    assert body["available"] is True
    assert body["backend"] == "in-memory"
    assert body["manifestsRebuilt"] >= 1
    assert body["leavesRebuilt"] == body["manifestsRebuilt"]
    # the recovery index reconstitutes from storage alone: the demo asset recovers against it
    assert body["demoRecovered"] is True
    assert body["demoSimilarity"] == 100


async def test_demo_rebuild_without_storage_is_honest() -> None:
    sbr.set_storage(None)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            body = (await c.get("/demo/rebuild")).json()
    finally:
        sbr.set_storage(None)
    assert body["available"] is False
    assert body["backend"] == "none"
    assert body["demoRecovered"] is False
