"""The recovery core: resolve a stripped asset back to its manifest.

Order matches the C2PA soft-binding model: try the watermark first (an exact pointer), fall back to
the PDQ fingerprint (nearest within Hamming 31). The cross-layer integrity check recomputes the
queried asset's fingerprint and confirms it matches the recovered manifest, closing the
"integrity clash" attack where a real manifest is returned for an unrelated asset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

from .fingerprint import compute_pdq, hamming, is_match
from .models import (
    ALG_TRUSTMARK_P,
    PDQ_HAMMING_THRESHOLD,
    Manifest,
    Match,
    SoftBindingQueryResult,
)
from .watermark import Watermarker


class Index(Protocol):
    def put_manifest(self, manifest: Manifest) -> None: ...
    def get_manifest(self, manifest_id: str) -> Manifest | None: ...
    def put_watermark_binding(self, watermark_id: str, manifest_id: str) -> None: ...
    def manifest_for_watermark(self, watermark_id: str) -> str | None: ...
    def put_fingerprint(self, pdq_bits: str, manifest_id: str) -> None: ...
    def nearest_fingerprint(self, pdq_bits: str, threshold: int) -> tuple[str, int] | None: ...
    def fingerprints_for(self, manifest_id: str) -> list[str]: ...
    def kind(self) -> str:
        """A short label of the backing store and search path, for the live status surface."""
        ...

    def register(self, manifest: Manifest, watermark_id: str, pdq_bits: str) -> None:
        """Atomically index a freshly generated asset (manifest, watermark binding, and PDQ
        together) so a partial ingest never leaves a manifest that cannot be recovered."""
        ...


@dataclass
class InMemoryIndex:
    """Scaffold index. Production index is Postgres (B-tree watermark_id, HNSW bit(256))."""

    manifests: dict[str, Manifest] = field(default_factory=dict)
    watermarks: dict[str, str] = field(default_factory=dict)
    fingerprints: list[tuple[str, str]] = field(default_factory=list)

    def put_manifest(self, manifest: Manifest) -> None:
        self.manifests[manifest.manifest_id] = manifest

    def get_manifest(self, manifest_id: str) -> Manifest | None:
        return self.manifests.get(manifest_id)

    def put_watermark_binding(self, watermark_id: str, manifest_id: str) -> None:
        # A watermark binding is immutable: once a watermark id points to a manifest, a later write
        # must not silently re-point it (that would poison recovery via /matches/byBinding). Mirrors
        # the Postgres ON CONFLICT (watermark_id) DO NOTHING. The API rejects re-points with a 409.
        self.watermarks.setdefault(watermark_id, manifest_id)

    def manifest_for_watermark(self, watermark_id: str) -> str | None:
        return self.watermarks.get(watermark_id)

    def put_fingerprint(self, pdq_bits: str, manifest_id: str) -> None:
        self.fingerprints.append((pdq_bits, manifest_id))

    def nearest_fingerprint(self, pdq_bits: str, threshold: int) -> tuple[str, int] | None:
        best: tuple[str, int] | None = None
        for bits, manifest_id in self.fingerprints:
            dist = hamming(pdq_bits, bits)
            if dist <= threshold and (best is None or dist < best[1]):
                best = (manifest_id, dist)
        return best

    def fingerprints_for(self, manifest_id: str) -> list[str]:
        return [bits for bits, mid in self.fingerprints if mid == manifest_id]

    def register(self, manifest: Manifest, watermark_id: str, pdq_bits: str) -> None:
        self.put_manifest(manifest)
        self.put_watermark_binding(watermark_id, manifest.manifest_id)
        self.put_fingerprint(pdq_bits, manifest.manifest_id)

    def kind(self) -> str:
        return "in-memory"


class Resolver:
    def __init__(self, index: Index, watermarker: Watermarker) -> None:
        self._index = index
        self._wm = watermarker

    def register(self, manifest: Manifest, image: Image.Image, watermark_id: str) -> None:
        """Index a freshly generated asset: store the manifest, its watermark binding, its PDQ.

        Delegates to the index's atomic register so a partial ingest cannot orphan a manifest."""
        bits, _ = compute_pdq(image)
        self._index.register(manifest, watermark_id, bits)

    def _fingerprint_matches(self, pdq_bits: str, manifest_id: str) -> bool:
        return any(is_match(pdq_bits, fp) for fp in self._index.fingerprints_for(manifest_id))

    def resolve_by_content(self, image: Image.Image) -> SoftBindingQueryResult:
        bits, _ = compute_pdq(image)
        # Watermark first, but only if the queried asset actually fingerprint-matches the pointed-to
        # manifest. This is the cross-layer integrity check applied inline: a watermark id that
        # points to an unrelated manifest (the "integrity clash") is rejected, not returned.
        watermark_id, _conf = self._wm.decode(image)
        if watermark_id is not None:
            manifest_id = self._index.manifest_for_watermark(watermark_id)
            if manifest_id is not None and self._fingerprint_matches(bits, manifest_id):
                return SoftBindingQueryResult(matches=[Match(manifest_id=manifest_id)])
        # PDQ fallback (already a fingerprint match, so integrity holds by construction).
        hit = self._index.nearest_fingerprint(bits, PDQ_HAMMING_THRESHOLD)
        if hit is not None:
            manifest_id, dist = hit
            score = round(100 * (1 - dist / 256))
            return SoftBindingQueryResult(
                matches=[Match(manifest_id=manifest_id, similarity_score=score)]
            )
        return SoftBindingQueryResult(matches=[])

    def resolve_by_binding(self, alg: str, value: str) -> SoftBindingQueryResult:
        if alg == ALG_TRUSTMARK_P:
            manifest_id = self._index.manifest_for_watermark(value)
            if manifest_id is not None:
                return SoftBindingQueryResult(matches=[Match(manifest_id=manifest_id)])
        return SoftBindingQueryResult(matches=[])

    def get_manifest(self, manifest_id: str) -> Manifest | None:
        return self._index.get_manifest(manifest_id)

    def check_integrity(self, manifest_id: str, image: Image.Image) -> bool:
        """Cross-layer check: does the queried asset fingerprint-match the recovered manifest?"""
        bits, _ = compute_pdq(image)
        return self._fingerprint_matches(bits, manifest_id)

    def index_kind(self) -> str:
        """The recovery index's backing store and search path, for the live status surface."""
        return self._index.kind()

    def close(self) -> None:
        """Release the index's resources (e.g. a Postgres pool); a no-op for the in-memory index."""
        close = getattr(self._index, "close", None)
        if callable(close):
            close()
