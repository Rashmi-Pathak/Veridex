"""TrustMark variant P watermark, behind a Protocol.

The real implementation pulls torch (heavy), so it lives behind the optional `watermark` extra and
is imported lazily. Unit tests use the in-process fake. The real watermark round-trip is validated
separately by the Gate 1 kill experiment harness.
"""

from __future__ import annotations

from typing import Protocol, cast

from PIL import Image


class Watermarker(Protocol):
    def encode(self, image: Image.Image, secret: str) -> Image.Image: ...
    def decode(self, image: Image.Image) -> tuple[str | None, float]: ...


class FakeWatermarker:
    """Deterministic stand-in for tests. decode() returns whatever id it was constructed with."""

    def __init__(self, decoded_id: str | None = None, confidence: float = 1.0) -> None:
        self._decoded_id = decoded_id
        self._confidence = confidence

    def encode(self, image: Image.Image, secret: str) -> Image.Image:
        return image

    def decode(self, image: Image.Image) -> tuple[str | None, float]:
        if self._decoded_id is None:
            return None, 0.0
        return self._decoded_id, self._confidence


class TrustMarkWatermarker:
    """Real TrustMark variant P (BCH_SUPER). Requires the `watermark` extra (trustmark + torch)."""

    def __init__(self) -> None:
        from trustmark import TrustMark

        # loadRemover=False: Rooted only encodes and decodes, never removes a watermark, so skip
        # downloading and loading the remover model.
        self._tm = TrustMark(
            verbose=False,
            model_type="P",
            encoding_type=TrustMark.Encoding.BCH_SUPER,
            loadRemover=False,
        )
        # Text mode packs 7-bit ASCII; BCH_SUPER carries 40 bits, so 5 chars. Query rather than
        # hardcode, since capacity depends on the encoding type.
        self._max_chars = self._tm.schemaCapacity() // 7

    def encode(self, image: Image.Image, secret: str) -> Image.Image:
        # The raw encoder silently truncates an over-long secret (e.g. "TOOLONG" -> "TOOLO\x13"),
        # which would corrupt the watermark id so it never matches the registry and recovery would
        # fail silently. Fail loudly at the boundary instead.
        if len(secret) > self._max_chars:
            raise ValueError(
                f"watermark id {secret!r} exceeds the BCH_SUPER text capacity of "
                f"{self._max_chars} chars; it would be silently truncated"
            )
        return cast(Image.Image, self._tm.encode(image.convert("RGB"), secret, MODE="text"))

    def decode(self, image: Image.Image) -> tuple[str | None, float]:
        secret, present, _schema = self._tm.decode(image.convert("RGB"), MODE="text")
        return (secret if present else None), (1.0 if present else 0.0)
