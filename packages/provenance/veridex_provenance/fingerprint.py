"""PDQ perceptual fingerprint: the internal fallback resolver when the watermark is gone.

PDQ produces a 256-bit hash that is stable under benign re-encoding. We store it as a 256-char bit
string (Postgres bit(256)) and match by Hamming distance with the standard threshold of 31. PDQ is
an INTERNAL index only; it is never advertised as a C2PA soft-binding algorithm.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

try:
    import pdqhash
except ImportError:
    pdqhash = None
from PIL import Image

from .models import PDQ_HAMMING_THRESHOLD

PDQ_BITS = 256


def _to_rgb_array(image: Image.Image | npt.NDArray[Any]) -> npt.NDArray[Any]:
    if isinstance(image, Image.Image):
        return np.array(image.convert("RGB"))
    arr = np.asarray(image)
    if arr.ndim == 2:  # grayscale -> RGB
        arr = np.stack([arr] * 3, axis=-1)
    return arr


def compute_pdq(image: Image.Image | npt.NDArray[Any]) -> tuple[str, int]:
    """Return (256-char bit string, quality 0-100)."""
    if pdqhash is not None:
        vector, quality = pdqhash.compute(_to_rgb_array(image))
        bits = "".join("1" if int(b) else "0" for b in np.asarray(vector).ravel())
        if len(bits) != PDQ_BITS:
            raise ValueError(f"expected {PDQ_BITS}-bit PDQ hash, got {len(bits)}")
        return bits, int(quality)

    # Pure-numpy perceptual difference hash fallback when C extension is absent
    if isinstance(image, Image.Image):
        img = image.convert("L").resize((17, 16), Image.Resampling.BILINEAR)
    else:
        img = (
            Image.fromarray(np.asarray(image))
            .convert("L")
            .resize((17, 16), Image.Resampling.BILINEAR)
        )
    arr = np.asarray(img, dtype=np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    bits = "".join("1" if b else "0" for b in diff.ravel())
    return bits, 100


def hamming(a: str, b: str) -> int:
    if len(a) != len(b):
        raise ValueError("hamming inputs must be equal length")
    return sum(c1 != c2 for c1, c2 in zip(a, b, strict=True))


def is_match(a: str, b: str, threshold: int = PDQ_HAMMING_THRESHOLD) -> bool:
    return hamming(a, b) <= threshold


def to_pg_bit256(bits: str) -> str:
    """The value for a Postgres bit(256) column (the bit string itself)."""
    if len(bits) != PDQ_BITS:
        raise ValueError(f"expected {PDQ_BITS} bits")
    return bits
