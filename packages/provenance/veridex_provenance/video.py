"""Video perceptual fingerprint: recover a video by per-keyframe PDQ.

The same idea as the image and audio modalities. A video is decoded to frames sampled at a fixed
rate (ffmpeg via imageio-ffmpeg, the same bundled binary the audio path uses), and each frame is
hashed with the existing image PDQ. A registered video keeps one fingerprint per sampled frame; a
query video is matched frame by frame. A re-encode preserves the content timeline, so the frame at
each sampled timestamp is the same image, and PDQ tolerates the re-encode, so any one frame match
recovers the manifest. Like PDQ for images, this is an INTERNAL index only; it is never advertised
as a C2PA soft-binding algorithm.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile

from PIL import Image, UnidentifiedImageError

from .audio import ffmpeg_exe

_MAX_VIDEO_BYTES = 100 * 1024 * 1024  # videos are larger than audio/images
_DECODE_TIMEOUT = 30.0
_MAX_FRAMES = 8  # bounds memory and the number of PDQs; an 8s clip sampled at 1 fps
_FPS = 1.0  # sample one frame per second (stable across a re-encode, which preserves timing)
_MAX_FRAME_DIM = 640  # cap BOTH frame dimensions; bounds memory, ample for a 64x64 PDQ downscale


class VideoDecodeError(ValueError):
    """Video could not be decoded to frames (bad/unsupported input, too large, or ffmpeg died)."""


def video_frames(data: bytes) -> list[Image.Image]:
    """Decode a video to up to _MAX_FRAMES sampled RGB frames via ffmpeg, failing closed.

    The bytes are written to a temp file and frames are written to a temp directory as PNGs; both
    paths are server-generated (no shell, argv list, so no path or shell injection). The decode is
    bounded by a wall-clock timeout and the input is size-capped before the write; the whole temp
    directory is always removed. Sampling at a fixed fps keeps the same content frames across a
    re-encode, which is what makes per-frame PDQ recovery stable.
    """
    if len(data) > _MAX_VIDEO_BYTES:
        raise VideoDecodeError("video exceeds the size cap")
    workdir = tempfile.mkdtemp(prefix="rootedvid")
    src = os.path.join(workdir, "in.bin")
    pattern = os.path.join(workdir, "f%03d.png")
    try:
        with open(src, "wb") as f:
            f.write(data)
        cmd = [
            ffmpeg_exe(),
            "-v",
            "error",
            "-nostdin",
            "-i",
            src,
            "-vf",
            # Sample at a fixed fps and fit each frame inside _MAX_FRAME_DIM x _MAX_FRAME_DIM
            # (downscale only, aspect preserved). Capping BOTH dimensions bounds memory: a tall or
            # wide crafted clip cannot balloon 8 frames into ~1 GB. PDQ downscales to 64x64 anyway.
            f"fps={_FPS},scale={_MAX_FRAME_DIM}:{_MAX_FRAME_DIM}:force_original_aspect_ratio=decrease",
            "-frames:v",
            str(_MAX_FRAMES),
            pattern,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=_DECODE_TIMEOUT)
        if proc.returncode != 0:
            raise VideoDecodeError("video could not be decoded")
        frames: list[Image.Image] = []
        for p in sorted(glob.glob(os.path.join(workdir, "f*.png"))):
            with Image.open(p) as im:
                frames.append(im.convert("RGB").copy())
        if not frames:
            raise VideoDecodeError("no frames extracted from the video")
        return frames
    except (
        subprocess.TimeoutExpired,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        # Fail closed as a decode error (-> 415) rather than 500, mirroring the image decode path.
        raise VideoDecodeError(f"video decode failed: {exc}") from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
