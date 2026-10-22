"""Tests for the audio recovery modality (the audio analog of the image SBR loop).

Network-free: in-memory image + audio resolvers, the audio demo seeded. The headline is that the
seeded demo audio, once re-encoded (the audio "strip"), recovers to its manifest by the perceptual
audio fingerprint, with the recovered manifest naming the real generator. Non-audio uploads are
rejected, and audio recovery uses a separate index so it never cross-matches an image.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterator
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from veridex_api import demo, sbr
from veridex_api.main import app
from veridex_provenance.audio import ffmpeg_exe
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker


@pytest.fixture
def client() -> Iterator[TestClient]:
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_audio_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(TransparencyLog())
    sbr.set_storage(None)
    demo.seed_audio_demo(sbr.get_audio_resolver(), sbr.get_log(), None)
    with TestClient(app) as c:
        yield c
    sbr.set_resolver(None)
    sbr.set_audio_resolver(None)
    sbr.set_log(None)
    sbr.set_storage(None)


def _reencode(data: bytes, args: list[str], ext: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".in", delete=False) as f:
        f.write(data)
        ipath = f.name
    opath = f"{ipath}.{ext}"
    try:
        subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", ipath, *args, opath], check=True)
        with open(opath, "rb") as out:
            return out.read()
    finally:
        for p in (ipath, opath):
            try:
                os.unlink(p)
            except OSError:
                pass


def test_audio_recovers_after_reencode(client: TestClient) -> None:
    orig = cast(Response, client.get("/demo/audio"))
    assert orig.status_code == 200
    assert orig.headers["content-type"] == "audio/mpeg"

    # The "strip": re-encode to a different codec, which destroys any embedded credential; recovery
    # is purely by the perceptual audio fingerprint.
    stripped = _reencode(orig.content, ["-c:a", "aac", "-b:a", "96k"], "m4a")
    rec = client.post(
        "/matches/byAudioContent", files={"file": ("stripped.m4a", stripped, "audio/mp4")}
    )
    assert rec.status_code == 200, rec.text
    matches = rec.json()["matches"]
    assert matches and matches[0]["manifestId"] == demo.DEMO_AUDIO_MANIFEST_ID

    # The recovered audio manifest is retrievable and names the real generator (no fiction).
    man = cast(Response, client.get(f"/manifests/{demo.DEMO_AUDIO_MANIFEST_ID}"))
    assert man.status_code == 200
    assert man.json()["systemProvenance"]["provider"] == "kie.ai-suno"


def test_audio_route_rejects_an_image(client: TestClient) -> None:
    # An image is not decodable as audio, so the audio route rejects it: no cross-modal nonsense.
    img = cast(Response, client.get("/demo/sample")).content
    rec = client.post("/matches/byAudioContent", files={"file": ("x.jpg", img, "image/jpeg")})
    assert rec.status_code == 415


def test_audio_route_rejects_garbage(client: TestClient) -> None:
    rec = client.post(
        "/matches/byAudioContent",
        files={"file": ("x.bin", b"this is not audio", "application/octet-stream")},
    )
    assert rec.status_code == 415
