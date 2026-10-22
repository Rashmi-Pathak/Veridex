"""SBR API: supportedAlgorithms hides PDQ, ingest then recover by content, redaction on read."""

from __future__ import annotations

import hashlib
import io

import httpx
import numpy as np
import pytest
from httpx import ASGITransport
from PIL import Image

from veridex_api.main import app


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    img = Image.fromarray(arr).resize((64, 64)).resize((256, 256))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_supported_algorithms_hides_pdq() -> None:
    async with _client() as c:
        r = await c.get("/services/supportedAlgorithms")
    assert r.status_code == 200
    assert "pdq" not in str(r.json()).lower()


async def test_ingest_then_recover_by_content() -> None:
    data = _png(7)
    async with _client() as c:
        ing = await c.post(
            "/ingest",
            files={"file": ("a.png", data, "image/png")},
            data={"manifest_id": "urn:c2pa:demo", "watermark_id": "RT07", "model": "seedream"},
        )
        assert ing.status_code == 200
        rec = await c.post("/matches/byContent", files={"file": ("a.png", data, "image/png")})
    assert rec.status_code == 200
    assert rec.json()["matches"][0]["manifestId"] == "urn:c2pa:demo"


async def test_get_manifest_is_redacted() -> None:
    data = _png(8)
    async with _client() as c:
        await c.post(
            "/ingest",
            files={"file": ("b.png", data, "image/png")},
            data={"manifest_id": "urn:c2pa:demo2", "watermark_id": "RT08", "model": "flux"},
        )
        r = await c.get("/manifests/urn:c2pa:demo2")
    assert r.status_code == 200
    body = r.json()
    assert body["systemProvenance"]["model"] == "flux"
    assert body["personalProvenance"] == {}
    assert body["assetSha256"] == hashlib.sha256(data).hexdigest()


async def test_unknown_manifest_404() -> None:
    async with _client() as c:
        r = await c.get("/manifests/urn:c2pa:nope")
    assert r.status_code == 404


async def test_disclosed_demo_manifest_hashes_to_its_transparency_leaf() -> None:
    # The bind that makes independent verification meaningful: the redacted manifest a client gets
    # from GET /manifests hashes IDENTICALLY to its transparency-log leaf, because the generation
    # prompt is PERSONAL provenance (excluded from the signed canonical), not system provenance.
    from veridex_api import sbr
    from veridex_api.demo import DEMO_MANIFEST_ID, seed_demo
    from veridex_provenance.merkle import TransparencyLog
    from veridex_provenance.resolver import InMemoryIndex, Resolver
    from veridex_provenance.watermark import FakeWatermarker

    resolver = Resolver(InMemoryIndex(), FakeWatermarker())
    log = TransparencyLog()
    sbr.set_resolver(resolver)
    sbr.set_log(log)
    try:
        seed_demo(resolver, log)
        stored = resolver.get_manifest(DEMO_MANIFEST_ID)
        assert stored is not None
        # the prompt is personal (withheld), never in the disclosed system provenance
        assert "prompt" not in stored.system_provenance
        assert stored.personal_provenance.get("prompt")
        leaf_hash = next(h for _i, mid, h in log.entries() if mid == DEMO_MANIFEST_ID)
        # the disclosed (redacted) manifest hashes to the exact logged leaf
        assert stored.redacted().canonical_hash() == leaf_hash
        assert stored.canonical_hash() == leaf_hash  # full == redacted (personal excluded)
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)


async def test_signed_manifest_does_not_disclose_the_prompt() -> None:
    # /demo/signed-manifest serves the REDACTED manifest: the generation prompt (personal) is never
    # disclosed, and the signature still verifies against it (canonical excludes personal).
    async with _client() as c:
        r = await c.get("/demo/signed-manifest")
    assert r.status_code == 200
    body = r.json()
    assert "prompt" not in body["manifest"].get("systemProvenance", {})
    assert body["manifest"].get("personalProvenance", {}) == {}


async def test_get_manifest_withholds_a_prompt_left_in_system_provenance() -> None:
    # A legacy/WORM-locked manifest carries the prompt in SYSTEM provenance (its signed hash is
    # sealed, so the manifest cannot change). The read route must still withhold the prompt while
    # disclosing the rest of system provenance. Newly signed manifests keep the prompt in personal
    # provenance instead, so this stripping is defensive cover for legacy records.
    from veridex_api.sbr import get_resolver
    from veridex_provenance.models import Manifest

    image = Image.open(io.BytesIO(_png(37))).convert("RGB")
    manifest = Manifest(
        manifest_id="urn:c2pa:legacy-prompt",
        asset_sha256=hashlib.sha256(_png(37)).hexdigest(),
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream", "provider": "gmi", "prompt": "a private prompt"},
    )
    get_resolver().register(manifest, image, "RTleg")
    async with _client() as c:
        r = await c.get("/manifests/urn:c2pa:legacy-prompt")
    assert r.status_code == 200
    body = r.json()
    assert "prompt" not in body["systemProvenance"]
    assert body["systemProvenance"] == {"model": "seedream", "provider": "gmi"}
    assert body["personalProvenance"] == {}


async def test_get_manifest_enforces_redaction_of_real_personal_provenance() -> None:
    # The ingest route never sets personal_provenance, so asserting it is empty after ingest is
    # vacuous. Register a manifest that actually carries PII, then prove the read route strips it
    # (this fails if get_manifest stops calling .redacted()).
    from veridex_api.sbr import get_resolver
    from veridex_provenance.models import Manifest

    image = Image.open(io.BytesIO(_png(31))).convert("RGB")
    manifest = Manifest(
        manifest_id="urn:c2pa:pii",
        asset_sha256=hashlib.sha256(_png(31)).hexdigest(),
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream"},
        personal_provenance={"prompt": "a private prompt", "user": "alice"},
    )
    get_resolver().register(manifest, image, "RTpii")
    async with _client() as c:
        r = await c.get("/manifests/urn:c2pa:pii")
    assert r.status_code == 200
    body = r.json()
    assert body["systemProvenance"]["model"] == "seedream"
    assert body["personalProvenance"] == {}


async def test_bycontent_rejects_decompression_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    # A tiny crafted image whose header declares huge dimensions must fail closed as 415, not crash
    # the public endpoint with a 500. DecompressionBombError is not an OSError, so it needs a catch.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 16)
    data = _png(3)  # 256x256 = 65536 pixels, well over 2x the patched limit
    async with _client() as c:
        r = await c.post("/matches/byContent", files={"file": ("a.png", data, "image/png")})
    assert r.status_code == 415


async def test_bycontent_rejects_oversized_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    import veridex_api.sbr as sbr

    monkeypatch.setattr(sbr, "_MAX_UPLOAD_BYTES", 8)
    async with _client() as c:
        r = await c.post("/matches/byContent", files={"file": ("a.png", _png(4), "image/png")})
    assert r.status_code == 413


def test_cap_matches_caps_only_when_supplied() -> None:
    # The C2PA SBR maxResults param caps the matches list; absent, the result is unchanged.
    from veridex_api.sbr import _cap_matches
    from veridex_provenance.models import Match, SoftBindingQueryResult

    full = SoftBindingQueryResult(matches=[Match(manifest_id=f"m{i}") for i in range(3)])
    assert len(_cap_matches(full, None).matches) == 3  # absent: unchanged (back-compat)
    assert len(_cap_matches(full, 5).matches) == 3  # larger than the count: unchanged
    assert [m.manifest_id for m in _cap_matches(full, 2).matches] == ["m0", "m1"]  # capped


async def test_bycontent_hint_cannot_forge_a_match_for_unmatched_content() -> None:
    # hintAlg + hintValue are ADVISORY only on /matches/byContent: they can never introduce a
    # manifest the uploaded CONTENT did not match. Uploading arbitrary bytes with a known binding
    # value must NOT forge a "recovered by content" result (that would let anyone claim provenance
    # for content they do not have). Binding-only recovery is /matches/byBinding, honestly named.
    from veridex_api.sbr import get_resolver
    from veridex_provenance.models import ALG_TRUSTMARK_P, Manifest

    image = Image.open(io.BytesIO(_png(50))).convert("RGB")
    manifest = Manifest(
        manifest_id="urn:c2pa:hint",
        asset_sha256=hashlib.sha256(_png(50)).hexdigest(),
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream"},
    )
    get_resolver().register(manifest, image, "RThintwm")

    other = _png(99)  # a different asset that does not content-match the registered one
    async with _client() as c:
        miss = await c.post("/matches/byContent", files={"file": ("o.png", other, "image/png")})
        # Same non-matching upload, but this time asserting the known binding as a hint.
        forged = await c.post(
            "/matches/byContent",
            files={"file": ("o.png", other, "image/png")},
            params={"hintAlg": ALG_TRUSTMARK_P, "hintValue": "RThintwm"},
        )
        # The genuine content DOES match with or without the hint; the hint only reorders.
        genuine = await c.post(
            "/matches/byContent",
            files={"file": ("m.png", _png(50), "image/png")},
            params={"hintAlg": ALG_TRUSTMARK_P, "hintValue": "RThintwm"},
        )
    assert miss.status_code == 200
    assert miss.json()["matches"] == []
    # The forge attempt returns the SAME empty result as without the hint: no fabricated match.
    assert forged.status_code == 200
    assert forged.json()["matches"] == []
    # The real asset still recovers, and the hinted+content-confirmed manifest is present.
    assert genuine.status_code == 200
    assert any(m["manifestId"] == "urn:c2pa:hint" for m in genuine.json()["matches"])


async def test_bybinding_maxresults_validates_and_passes_through() -> None:
    # maxResults must be >= 1 (else 422) and, when satisfiable, does not change a single result.
    from veridex_api.sbr import get_resolver
    from veridex_provenance.models import ALG_TRUSTMARK_P, Manifest

    image = Image.open(io.BytesIO(_png(51))).convert("RGB")
    manifest = Manifest(
        manifest_id="urn:c2pa:cap",
        asset_sha256=hashlib.sha256(_png(51)).hexdigest(),
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream"},
    )
    get_resolver().register(manifest, image, "RTcapwm")
    base = {"alg": ALG_TRUSTMARK_P, "value": "RTcapwm"}
    async with _client() as c:
        bad = await c.get("/matches/byBinding", params={**base, "maxResults": 0})
        ok = await c.get("/matches/byBinding", params={**base, "maxResults": 1})
    assert bad.status_code == 422  # ge=1 rejects 0
    assert ok.status_code == 200
    assert ok.json()["matches"][0]["manifestId"] == "urn:c2pa:cap"
