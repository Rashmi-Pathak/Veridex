"""Watermarker: the in-process fake (always), and the real TrustMark variant P round-trip.

The real-library tests need the `watermark` extra (trustmark + torch), which CI does not install
(CI runs `uv sync --all-packages`, not `--all-extras`). They are skipped when trustmark is absent,
so CI stays green and fast; run them locally with `uv sync --extra watermark` to verify the real
encode -> decode loop and that the watermark survives the pipeline's own JPEG re-encode.

Carrier note: the two trust layers have opposite carrier needs. TrustMark embeds in natural
mid-frequency content (a smooth gradient works; random noise does not), while PDQ needs real
structure to produce a stable hash (a flat gradient gives a low-quality, fragile hash). So the tests
use a synthetic-but-representative carrier (smooth gradient + soft blobs + mild texture) that has
both, which is what real generated media looks like. The full loop on real generated images is
exercised separately by the live ingest script once a provider is funded. A pristine image can also
spuriously decode as "present" with a garbage payload; that is harmless for Rooted because a
watermark id is trusted only after it matches a stored manifest AND the asset fingerprint-matches it
(the resolver's cross-layer check).
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from veridex_provenance.models import Manifest
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker, TrustMarkWatermarker

try:
    # An actual import, not importlib.util.find_spec: when uv removes the extra it can leave an
    # empty `trustmark` namespace dir, so find_spec returns a (useless) spec while `from trustmark
    # import TrustMark` still fails. Importing the symbol also confirms torch and the rest present.
    from trustmark import TrustMark  # noqa: F401

    _HAS_TRUSTMARK = True
except ImportError:
    _HAS_TRUSTMARK = False

real_only = pytest.mark.skipif(
    not _HAS_TRUSTMARK, reason="needs the `watermark` extra (trustmark + torch)"
)


def _carrier(seed: int = 7, size: int = 256) -> Image.Image:
    """A representative image: smooth gradient + soft blobs + mild texture. Mid-frequency content
    for TrustMark and enough structure for a stable, high-quality PDQ hash."""
    rng = np.random.default_rng(seed)
    ramp = np.linspace(0, 255, size)
    img = np.stack(
        [np.tile(ramp, (size, 1)), np.tile(ramp[:, None], (1, size)), np.full((size, size), 128.0)],
        axis=-1,
    )
    yy, xx = np.mgrid[0:size, 0:size]
    for _ in range(6):
        cy, cx = rng.integers(0, size, 2)
        r = rng.integers(20, 70)
        blob = np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * r * r))
        img += blob[..., None] * rng.integers(-80, 80, 3)
    img += rng.normal(0, 6, (size, size, 3))
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


# --- the fake (always runs, no heavy deps) ---


def test_fake_decode_returns_constructed_id() -> None:
    wm = FakeWatermarker(decoded_id="RT01", confidence=0.9)
    img = _carrier()
    assert wm.encode(img, "RT01") is img  # identity
    assert wm.decode(img) == ("RT01", 0.9)


def test_fake_absent_decodes_to_none() -> None:
    assert FakeWatermarker().decode(_carrier()) == (None, 0.0)


# --- the real TrustMark variant P (only with the `watermark` extra) ---


@pytest.fixture(scope="module")
def real_wm() -> TrustMarkWatermarker:
    return TrustMarkWatermarker()


@real_only
def test_real_roundtrip_recovers_secret(real_wm: TrustMarkWatermarker) -> None:
    secret = "RT01"  # 4 chars, within BCH_SUPER text capacity (40 bits / 7 = 5 chars)
    watermarked = real_wm.encode(_carrier(), secret)
    recovered, conf = real_wm.decode(watermarked)
    assert recovered == secret
    assert conf == 1.0


@real_only
def test_real_survives_jpeg_q90(real_wm: TrustMarkWatermarker) -> None:
    """The load-bearing path: the pipeline stores the watermarked asset as JPEG q90, so the mark
    must survive that re-encode for byBinding recovery to work."""
    secret = "RT42"
    watermarked = real_wm.encode(_carrier(), secret)
    buf = io.BytesIO()
    watermarked.save(buf, "JPEG", quality=90)
    buf.seek(0)
    recovered, _ = real_wm.decode(Image.open(buf))
    assert recovered == secret


@real_only
def test_real_over_capacity_secret_raises(real_wm: TrustMarkWatermarker) -> None:
    """A too-long id must fail loudly, not silently truncate: the raw encoder turns 'TOOLONG' into
    'TOOLO\\x13', and that corrupted id would never match the registry, so recovery would fail
    silently. Guard it at the boundary instead."""
    with pytest.raises(ValueError, match="capacity"):
        real_wm.encode(_carrier(), "TOOLONG")


@real_only
def test_real_watermark_recovers_through_resolver(real_wm: TrustMarkWatermarker) -> None:
    """The closed loop on real data: enroll a real watermarked asset, then recover it through the
    full resolver path (watermark decode -> registry lookup -> PDQ cross-layer check) after the
    pipeline's JPEG q90 re-encode has stripped any embedded manifest."""
    resolver = Resolver(InMemoryIndex(), real_wm)
    manifest = Manifest(
        manifest_id="urn:c2pa:abcd1234-0000-0000-0000-000000000000",
        asset_sha256="a" * 64,
        created_at="2026-06-25T00:00:00Z",
        system_provenance={"model": "seedream"},
    )
    watermarked = real_wm.encode(_carrier(), "RT01")
    resolver.register(manifest, watermarked, watermark_id="RT01")

    buf = io.BytesIO()
    watermarked.save(buf, "JPEG", quality=90)  # the asset that later circulates, manifest stripped
    buf.seek(0)
    stripped = Image.open(buf)

    result = resolver.resolve_by_content(stripped)
    assert [m.manifest_id for m in result.matches] == [manifest.manifest_id]
