"""The image-decode concurrency limiter (veridex_api.sbr._image_decode_limiter).

The audio and video decode paths bound how many decodes run at once (so a burst cannot pin the
threadpool or OOM the lean instance); the public image path must do the same. This asserts the
wiring deterministically: _read_image dispatches the decode under _image_decode_limiter.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import anyio
import pytest
from fastapi import UploadFile
from PIL import Image

from veridex_api import sbr


def _png_bytes(size: int = 16) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (123, 50, 200)).save(buf, "PNG")
    return buf.getvalue()


def test_image_decode_limiter_default_tokens() -> None:
    assert isinstance(sbr._image_decode_limiter, anyio.CapacityLimiter)
    assert sbr._image_decode_limiter.total_tokens == 4


async def test_read_image_dispatches_under_the_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    real_run_sync = anyio.to_thread.run_sync

    async def spy(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        # The decode is the call that carries a limiter kwarg; record it, then run for real.
        if "limiter" in kwargs:
            captured["limiter"] = kwargs["limiter"]
        return await real_run_sync(func, *args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", spy)
    upload = UploadFile(filename="a.png", file=io.BytesIO(_png_bytes()))
    image = await sbr._read_image(upload)

    assert image.size == (16, 16)
    assert captured.get("limiter") is sbr._image_decode_limiter
