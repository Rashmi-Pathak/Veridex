"""Tests for the video recovery modality (per-keyframe PDQ).

Network-free: in-memory resolvers, the video demo seeded. The headline is that the seeded demo
video, once re-encoded (the video "strip"), recovers to its manifest because at least one sampled
frame's fingerprint still matches. Cross-modal isolation holds: a video is rejected by the image
route, and garbage is rejected by the video route.
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
    sbr.set_video_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(TransparencyLog())
    sbr.set_storage(None)
    demo.seed_video_demo(sbr.get_video_resolver(), sbr.get_log(), None)
    with TestClient(app) as c:
        yield c
    sbr.set_resolver(None)
    sbr.set_audio_resolver(None)
    sbr.set_video_resolver(None)
    sbr.set_log(None)
    sbr.set_storage(None)


def _reencode(data: bytes, args: list[str]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".in", delete=False) as f:
        f.write(data)
        ipath = f.name
    opath = f"{ipath}.out.mp4"
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


def test_video_recovers_after_reencode(client: TestClient) -> None:
    orig = cast(Response, client.get("/demo/video"))
    assert orig.status_code == 200
    assert orig.headers["content-type"] == "video/mp4"

    # The "strip": re-encode at a smaller scale and higher compression, which drops any embedded
    # credential; recovery is by per-keyframe PDQ.
    stripped = _reencode(
        orig.content, ["-vf", "scale=-2:480", "-c:v", "libx264", "-crf", "30", "-an"]
    )
    rec = client.post(
        "/matches/byVideoContent", files={"file": ("stripped.mp4", stripped, "video/mp4")}
    )
    assert rec.status_code == 200, rec.text
    matches = rec.json()["matches"]
    assert matches and matches[0]["manifestId"] == demo.DEMO_VIDEO_MANIFEST_ID

    man = cast(Response, client.get(f"/manifests/{demo.DEMO_VIDEO_MANIFEST_ID}"))
    assert man.status_code == 200
    assert man.json()["systemProvenance"]["provider"] == "kie.ai-veo3"


def test_image_route_rejects_a_video(client: TestClient) -> None:
    # A video is not a single image, so the image route rejects it (no cross-modal mix).
    video = cast(Response, client.get("/demo/video")).content
    rec = client.post("/matches/byContent", files={"file": ("x.mp4", video, "video/mp4")})
    assert rec.status_code == 415


def test_video_route_rejects_garbage(client: TestClient) -> None:
    rec = client.post(
        "/matches/byVideoContent",
        files={"file": ("x.bin", b"this is not a video at all", "application/octet-stream")},
    )
    assert rec.status_code == 415
