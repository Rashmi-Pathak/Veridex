"""The API resolver's watermarker selection: the fake by default (recovery runs on the PDQ path),
the real TrustMark only when opted in (VERIDEX_REAL_WATERMARK=1) and the `watermark` extra is there.
Importing real TrustMark pulls torch, so it is opt-in to keep the default deploy lean."""

from __future__ import annotations

import pytest

from veridex_api.sbr import _make_watermarker
from veridex_provenance.watermark import FakeWatermarker

try:
    # Import the symbol TrustMarkWatermarker actually uses (this also needs torch), not just the
    # top-level package, which can linger as an empty namespace dir after the extra is pruned.
    from trustmark import TrustMark  # noqa: F401

    _HAS_TRUSTMARK = True
except ImportError:
    _HAS_TRUSTMARK = False


def test_defaults_to_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIDEX_REAL_WATERMARK", raising=False)
    assert isinstance(_make_watermarker(), FakeWatermarker)


@pytest.mark.skipif(_HAS_TRUSTMARK, reason="this asserts the fallback when the extra is absent")
def test_falls_back_to_fake_without_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIDEX_REAL_WATERMARK", "1")
    assert isinstance(_make_watermarker(), FakeWatermarker)


@pytest.mark.skipif(not _HAS_TRUSTMARK, reason="needs the `watermark` extra (trustmark + torch)")
def test_uses_real_trustmark_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from veridex_provenance.watermark import TrustMarkWatermarker

    monkeypatch.setenv("VERIDEX_REAL_WATERMARK", "1")
    assert isinstance(_make_watermarker(), TrustMarkWatermarker)
