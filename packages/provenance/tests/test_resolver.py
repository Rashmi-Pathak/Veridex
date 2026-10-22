"""Recovery: watermark hit, PDQ fallback after stripping, integrity clash rejected, no false hit."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from veridex_provenance.models import ALG_TRUSTMARK_P, Manifest
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker


def _img(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    return Image.fromarray(arr).resize((64, 64)).resize((256, 256))


def _manifest(n: int) -> Manifest:
    return Manifest(
        manifest_id=f"urn:c2pa:0000000{n}-0000-0000-0000-000000000000",
        asset_sha256=f"{n:064d}",
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream"},
    )


def test_watermark_hit_recovers_manifest() -> None:
    index = InMemoryIndex()
    resolver = Resolver(index, FakeWatermarker(decoded_id="RT42"))
    m, img = _manifest(1), _img(1)
    resolver.register(m, img, watermark_id="RT42")
    result = resolver.resolve_by_content(img)
    assert [x.manifest_id for x in result.matches] == [m.manifest_id]


def test_pdq_fallback_after_watermark_stripped() -> None:
    index = InMemoryIndex()
    # the watermark decoder returns nothing (simulating a stripped screenshot)
    resolver = Resolver(index, FakeWatermarker(decoded_id=None))
    m, img = _manifest(2), _img(2)
    resolver.register(m, img, watermark_id="RT99")
    # re-encode the asset (manifest gone), recovery must still find it via PDQ
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    buf.seek(0)
    stripped = Image.open(buf)
    result = resolver.resolve_by_content(stripped)
    assert result.matches and result.matches[0].manifest_id == m.manifest_id
    assert result.matches[0].similarity_score is not None


def test_resolve_by_binding() -> None:
    index = InMemoryIndex()
    resolver = Resolver(index, FakeWatermarker())
    m, img = _manifest(3), _img(3)
    resolver.register(m, img, watermark_id="RT07")
    assert (
        resolver.resolve_by_binding(ALG_TRUSTMARK_P, "RT07").matches[0].manifest_id == m.manifest_id
    )
    assert resolver.resolve_by_binding(ALG_TRUSTMARK_P, "nope").matches == []


def test_unrelated_asset_does_not_match() -> None:
    index = InMemoryIndex()
    resolver = Resolver(index, FakeWatermarker(decoded_id=None))
    resolver.register(_manifest(4), _img(4), watermark_id="RTAA")
    result = resolver.resolve_by_content(_img(987))
    assert result.matches == []


def test_integrity_clash_rejected() -> None:
    index = InMemoryIndex()
    resolver = Resolver(index, FakeWatermarker())
    m, img = _manifest(5), _img(5)
    resolver.register(m, img, watermark_id="RTBB")
    assert resolver.check_integrity(m.manifest_id, img) is True
    assert resolver.check_integrity(m.manifest_id, _img(654)) is False


def test_watermark_clash_via_resolve_is_rejected() -> None:
    # A watermark decodes to "WX" pointing to manifest A, but the queried asset is unrelated. The
    # inline integrity check must reject it rather than return A (the integrity-clash defense).
    index = InMemoryIndex()
    resolver = Resolver(index, FakeWatermarker(decoded_id="WX"))
    m_a, img_a = _manifest(6), _img(6)
    resolver.register(m_a, img_a, watermark_id="WX")
    assert resolver.resolve_by_content(_img(777)).matches == []
    # the genuine asset still resolves
    assert resolver.resolve_by_content(img_a).matches[0].manifest_id == m_a.manifest_id


def test_close_delegates_to_index_close() -> None:
    closed: list[bool] = []

    class _ClosableIndex(InMemoryIndex):
        def close(self) -> None:
            closed.append(True)

    Resolver(_ClosableIndex(), FakeWatermarker()).close()
    assert closed == [True]


def test_close_is_noop_when_index_has_no_close() -> None:
    Resolver(InMemoryIndex(), FakeWatermarker()).close()  # in-memory has no close; must not raise
