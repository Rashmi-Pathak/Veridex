"""A Watermarker backed by the Rooted watermark service (infra/modal/watermark_service.py).

The lean API deploy carries no torch, so the real TrustMark model cannot run in-process there.
When VERIDEX_WATERMARK_REMOTE_URL and VERIDEX_WATERMARK_REMOTE_TOKEN are set, this client provides
the same Watermarker protocol over HTTP against the dedicated model service, and the
remark-failover demonstration runs both halves live in production. Every call is a real remote
inference; failures raise so callers degrade honestly instead of fabricating a verdict.
"""

from __future__ import annotations

import io
import os

import httpx
from PIL import Image

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def remote_watermark_config() -> tuple[str, str] | None:
    """(base_url, token) when the remote watermark service is configured, else None."""
    url = os.environ.get("VERIDEX_WATERMARK_REMOTE_URL", "").rstrip("/")
    token = os.environ.get("VERIDEX_WATERMARK_REMOTE_TOKEN", "")
    if not url or not token:
        return None
    return url, token


class RemoteWatermarker:
    """TrustMark P embed and decode over the authenticated model service."""

    def __init__(self, base_url: str, token: str, client: httpx.Client | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-Veridex-Token": token}
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def _png_bytes(self, image: Image.Image) -> bytes:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "PNG")
        return buf.getvalue()

    def encode(self, image: Image.Image, secret: str) -> Image.Image:
        r = self._client.post(
            f"{self._base}/embed",
            headers=self._headers,
            files={"file": ("asset.png", self._png_bytes(image), "image/png")},
            data={"watermark_id": secret},
        )
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")

    def decode(self, image: Image.Image) -> tuple[str | None, float]:
        r = self._client.post(
            f"{self._base}/decode",
            headers=self._headers,
            files={"file": ("asset.png", self._png_bytes(image), "image/png")},
        )
        r.raise_for_status()
        body = r.json()
        decoded = body.get("decodedId")
        confidence = body.get("confidence", 0.0)
        return (decoded if isinstance(decoded, str) and decoded else None), float(confidence)
