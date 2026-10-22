"""PDQ fingerprint: stable on the same image, robust to re-encode, distinct across images."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from veridex_provenance.fingerprint import compute_pdq, hamming, is_match


def _img(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    # smooth it so PDQ has real low-frequency structure, not pure noise
    img = Image.fromarray(base).resize((64, 64)).resize((256, 256))
    return img


def test_pdq_is_256_bits_and_stable() -> None:
    img = _img(1)
    a, qa = compute_pdq(img)
    b, _ = compute_pdq(img)
    assert len(a) == 256
    assert 0 <= qa <= 100
    assert a == b  # deterministic on identical input


def test_pdq_survives_jpeg_reencode() -> None:
    img = _img(2)
    original, _ = compute_pdq(img)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    buf.seek(0)
    reencoded, _ = compute_pdq(Image.open(buf))
    assert is_match(original, reencoded)  # within Hamming 31


def test_different_images_do_not_match() -> None:
    a, _ = compute_pdq(_img(10))
    b, _ = compute_pdq(_img(99))
    assert hamming(a, b) > 31


def test_hamming_length_guard() -> None:
    import pytest

    with pytest.raises(ValueError):
        hamming("0" * 256, "0" * 255)
