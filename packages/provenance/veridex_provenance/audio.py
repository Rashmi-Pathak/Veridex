"""Audio perceptual fingerprint: the audio analog of the image PDQ fallback resolver.

The recovery threat is the same as for images: an asset is re-encoded (mp3/aac/ogg, a sample-rate
change) and stripped of any embedded credential, and we recover its manifest by a perceptual match.
The approach reuses the image core verbatim. Decode the audio to canonical mono PCM with ffmpeg,
compute a log-mel spectrogram in pure numpy (no scipy / librosa / torch), render it as a grayscale
image, and hash THAT image with the same pdqhash used for pictures (compute_pdq). A re-encode leaves
the spectrogram (and so the 256-bit hash) almost unchanged, while an unrelated clip is far away, so
the existing bit-string Hamming index recovers audio with no new matcher and no new dependency.

Like PDQ, this is an INTERNAL index only; it is never advertised as a C2PA soft-binding algorithm.

Empirically gated (Gate-1-audio, on a real Suno clip with this pure-numpy pipeline): re-encode
distances (mp3 64-192k, aac, resample) were <= 20/256 while an unrelated clip sat at ~98/256, so the
image Hamming threshold of 31 recovers re-encodes with margin.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np
import numpy.typing as npt
from PIL import Image

_SR = 16000  # canonical mono sample rate; decoding to it neutralizes the sample-rate-change attack
_SECONDS = 10.0  # canonical analysis window (a fixed duration, so the global hash aligns)
_N_FFT = 1024
_HOP = 256
_N_MELS = 128
_MAX_AUDIO_BYTES = 25 * 1024 * 1024
# A 10s analysis window decodes well under 10s of wall-clock, so a short timeout bounds the hold on
# the decode worker (the SBR route also caps how many decodes run at once).
_DECODE_TIMEOUT = 10.0


class AudioDecodeError(ValueError):
    """Audio could not be decoded to PCM (bad or unsupported input, too large, or ffmpeg failed)."""


_ffmpeg_path: str | None = None


def ffmpeg_exe() -> str:
    """The ffmpeg executable path. Prefer imageio-ffmpeg's bundled static binary, so a lean deploy
    and CI need no system ffmpeg; fall back to a system 'ffmpeg' on PATH. Cached."""
    global _ffmpeg_path
    if _ffmpeg_path is None:
        try:
            import imageio_ffmpeg

            _ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001 - any failure resolving the bundled binary -> system ffmpeg
            _ffmpeg_path = "ffmpeg"
    return _ffmpeg_path


def _decode_pcm(data: bytes) -> npt.NDArray[np.float32]:
    """Decode arbitrary audio bytes to canonical mono float PCM via ffmpeg, failing closed.

    The bytes are written to a temp file (a seekable input, so every container including mp4/m4a
    decodes, unlike a non-seekable stdin pipe) whose name is server-controlled; ffmpeg is invoked as
    an argv list with no shell, so there is no path or shell injection. The decode is bounded by a
    wall-clock timeout, and the input size is capped before it is written. Decoding to a fixed mono
    sample rate neutralizes container, codec, channel, and sample-rate differences in one step (the
    normalization Chromaprint also does), which is what makes the fingerprint re-encode-stable.
    """
    if len(data) > _MAX_AUDIO_BYTES:
        raise AudioDecodeError("audio exceeds the size cap")
    # mkstemp yields the path up front, so a single finally always unlinks it, even if the write
    # itself fails (a NamedTemporaryFile whose write raised before name capture would leak).
    fd, path = tempfile.mkstemp(suffix=".audioin")
    cmd = [
        ffmpeg_exe(),
        "-v",
        "error",
        "-nostdin",
        "-i",
        path,
        "-ac",
        "1",
        "-ar",
        str(_SR),
        "-t",
        str(_SECONDS),
        "-f",
        "f32le",
        "pipe:1",
    ]
    try:
        with os.fdopen(fd, "wb") as tf:
            tf.write(data)
        proc = subprocess.run(cmd, capture_output=True, timeout=_DECODE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise AudioDecodeError(f"ffmpeg decode failed: {exc}") from exc
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if proc.returncode != 0 or not proc.stdout:
        raise AudioDecodeError("audio could not be decoded")
    x = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    n = int(_SR * _SECONDS)
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    return x[:n]


def _mel_filterbank() -> npt.NDArray[np.float64]:
    def hz2mel(f: float) -> float:
        return 2595.0 * float(np.log10(1.0 + f / 700.0))

    def mel2hz(m: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    pts = np.linspace(hz2mel(0.0), hz2mel(_SR / 2), _N_MELS + 2)
    freqs = mel2hz(pts)
    bins = np.floor((_N_FFT + 1) * freqs / _SR).astype(int)
    fb = np.zeros((_N_MELS, _N_FFT // 2 + 1))
    for i in range(1, _N_MELS + 1):
        lo, ce, hi = bins[i - 1], bins[i], bins[i + 1]
        for j in range(lo, ce):
            if ce > lo:
                fb[i - 1, j] = (j - lo) / (ce - lo)
        for j in range(ce, hi):
            if hi > ce:
                fb[i - 1, j] = (hi - j) / (hi - ce)
    return fb


_FB = _mel_filterbank()
_WINDOW = np.hanning(_N_FFT).astype(np.float32)


def _stft_power(x: npt.NDArray[np.float32]) -> npt.NDArray[np.float64]:
    """Magnitude-squared STFT in pure numpy (framed Hann windows + rfft), no scipy."""
    n_frames = max(1, 1 + (len(x) - _N_FFT) // _HOP)
    idx = np.arange(_N_FFT)[None, :] + _HOP * np.arange(n_frames)[:, None]
    idx = np.clip(idx, 0, len(x) - 1)
    frames = x[idx] * _WINDOW  # (n_frames, n_fft)
    spec = np.fft.rfft(frames, axis=1)
    return np.asarray(np.abs(spec) ** 2).T  # (n_freqs, n_frames)


def audio_to_image(data: bytes) -> Image.Image:
    """Decode audio and render its log-mel spectrogram as a grayscale image, ready for compute_pdq.

    The same pipeline runs on the original and on any re-encode, so the two images (and their PDQ
    hashes) match. The image is grayscale; compute_pdq promotes it to RGB, so it slots into the
    existing fingerprint path unchanged.
    """
    x = _decode_pcm(data)
    mel = _FB @ _stft_power(x)
    # Peak-relative log power in dB, floored at -80 dB. Anchoring to the peak removes absolute-level
    # sensitivity, and the floor drops the near-silence bins (which a re-encode perturbs most), so
    # the rendered image (and its PDQ hash) stays stable under re-encode rather than tracking the
    # quietest, noisiest cell of the spectrogram (which a min-max stretch would).
    db = 10.0 * np.log10(mel / (float(mel.max()) + 1e-12) + 1e-12)
    db = np.clip(db, -80.0, 0.0)
    g = ((db + 80.0) / 80.0 * 255.0).astype(np.uint8)
    return Image.fromarray(g, mode="L")
