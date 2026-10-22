"""The demo seed writes each asset/manifest/signature to the object store (B2 in prod) when one is
configured, and /demo/storage reports it. Uses the in-memory storage fake; the real B2 path is
exercised by the live deploy and a local smoke."""

from __future__ import annotations

import hashlib

import httpx
from httpx import ASGITransport

from veridex_api import sbr
from veridex_api.demo import (
    _PROVIDERS,
    DEMO_MANIFEST_ID,
    demo_sample_bytes,
    seed_demo,
    seed_providers,
)
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.models import Manifest
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.signing import verify_manifest
from veridex_provenance.watermark import FakeWatermarker
from veridex_storage.storage import (
    InMemoryStorage,
    asset_key,
    manifest_key,
    signature_key,
)


def _fresh() -> tuple[Resolver, TransparencyLog, InMemoryStorage]:
    return Resolver(InMemoryIndex(), FakeWatermarker()), TransparencyLog(), InMemoryStorage()


def test_seed_writes_asset_manifest_signature_to_storage() -> None:
    resolver, log, storage = _fresh()
    seed_demo(resolver, log, storage)
    sha = hashlib.sha256(demo_sample_bytes()).hexdigest()
    assert storage.exists(asset_key(sha))
    assert storage.exists(manifest_key(DEMO_MANIFEST_ID))
    assert storage.exists(signature_key(DEMO_MANIFEST_ID))


def test_seed_without_storage_stays_in_memory() -> None:
    resolver, log, _ = _fresh()
    seed_demo(resolver, log)  # no storage arg
    assert resolver.get_manifest(DEMO_MANIFEST_ID) is not None


async def test_demo_storage_route_reports_present_objects() -> None:
    resolver, log, storage = _fresh()
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    sbr.set_storage(storage)
    seed_demo(resolver, log, storage)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/demo/storage")
            assert r.status_code == 200
            body = r.json()
            assert body["backend"] == "in-memory"
            assert body["present"]["asset"]
            assert body["present"]["manifest"]
            assert body["present"]["signature"]
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)
        sbr.set_storage(None)


def test_b2_image_signature_verifies_against_published_key() -> None:
    # The durable COSE signature stored in B2 must verify against the SAME public key the API
    # publishes (/transparency/checkpoint, /status), not a discarded throwaway key, or the stored
    # artifact is unverifiable by anyone (the recovery-repository claim would be hollow).
    resolver, log, storage = _fresh()
    seed_demo(resolver, log, storage)
    cose = storage.get(signature_key(DEMO_MANIFEST_ID))
    manifest = Manifest.model_validate_json(storage.get(manifest_key(DEMO_MANIFEST_ID)))
    assert verify_manifest(cose, manifest, sbr.signing_public_key()) is True


def test_b2_provider_signature_verifies_against_published_key() -> None:
    # Same guarantee for the multi-provider seeds (the other _register path).
    resolver, log, storage = _fresh()
    seed_providers(resolver, log, storage)
    mid = _PROVIDERS[0]["manifest_id"]
    cose = storage.get(signature_key(mid))
    manifest = Manifest.model_validate_json(storage.get(manifest_key(mid)))
    assert verify_manifest(cose, manifest, sbr.signing_public_key()) is True
