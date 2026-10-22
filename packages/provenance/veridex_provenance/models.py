"""Shared provenance contracts and canonicalization.

Every component (storage, fingerprint, signing, claim, Merkle log, the SBR API) builds against
these models. The canonical hash is the deterministic anchor: a manifest is serialized to canonical
JSON (sorted keys, no insignificant whitespace, UTF-8) and SHA-256'd. The same bytes are what we
sign and what we add to the Merkle log, so the three layers agree by construction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# C2PA soft-binding algorithm identifiers. TrustMark variant P is the registered watermark we
# advertise. PDQ is an INTERNAL index only and is never listed in SupportedAlgorithms.
ALG_TRUSTMARK_P = "com.adobe.trustmark.P"
PDQ_HAMMING_THRESHOLD = 31


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, compact separators, UTF-8. The hashing input."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CamelModel(BaseModel):
    """Base for the JSON API contract: serialize to camelCase (the C2PA SBR spec style) while still
    accepting and constructing by snake_case field name internally. model_dump() stays snake_case by
    default, so storage, canonical hashing, and signing are unaffected; only HTTP responses (which
    FastAPI serializes by alias) emit camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SoftBinding(CamelModel):
    """A recoverable pointer from an asset to its manifest (a watermark ID or a fingerprint)."""

    alg: str
    value: str
    scope: str = "all"


# Personal-provenance keys that can appear in system_provenance on a legacy/WORM-locked manifest
# (e.g. a prompt). The disclosure layer (Manifest.redacted) withholds them; the full signed manifest
# stays the verifiable artifact, anchored in the transparency log and the Object-Lock checkpoint.
_PERSONAL_SYSTEM_KEYS = frozenset({"prompt"})


class Manifest(CamelModel):
    """The provenance record Rooted stores and recovers.

    system_provenance is disclosed on recovery (model, provider, timestamp). personal_provenance
    (prompt, user, IP) is withheld by the SB 942-style redaction layer. soft_bindings carry the
    watermark ID and the PDQ fingerprint used to recover this manifest when the asset is stripped.
    """

    manifest_id: str
    asset_sha256: str
    created_at: str
    system_provenance: dict[str, Any] = Field(default_factory=dict)
    personal_provenance: dict[str, Any] = Field(default_factory=dict)
    soft_bindings: list[SoftBinding] = Field(default_factory=list)

    def canonical_payload(self) -> dict[str, Any]:
        """The fields that are bound by the canonical hash and the signature.

        personal_provenance is EXCLUDED, so clearing it (the common redaction) does not change the
        hash. soft_bindings are excluded too: they are recovery pointers maintained alongside the
        manifest, not part of its identity. The verifiable artifact is the FULL signed manifest; the
        /manifests disclosure view may additionally withhold personal keys (see redacted()).
        """
        return {
            "manifest_id": self.manifest_id,
            "asset_sha256": self.asset_sha256,
            "created_at": self.created_at,
            "system_provenance": self.system_provenance,
        }

    def canonical_hash(self) -> str:
        return sha256_hex(canonical_json(self.canonical_payload()))

    def redacted(self) -> Manifest:
        """The SB 942 disclosure view: emit system provenance, withhold personal provenance. Clears
        personal_provenance AND strips any personal key (e.g. a prompt) that appears in
        system_provenance on a legacy manifest. This is a read-time privacy transform on the
        DISCLOSURE only: the full signed manifest is unchanged and stays the verifiable artifact,
        anchored in the transparency log and the Object-Lock checkpoint."""
        system = {k: v for k, v in self.system_provenance.items() if k not in _PERSONAL_SYSTEM_KEYS}
        return self.model_copy(update={"personal_provenance": {}, "system_provenance": system})


class Match(CamelModel):
    """One SBR query result: a manifest the queried asset binds to."""

    manifest_id: str
    similarity_score: int | None = None  # 0-100; None for an exact watermark hit
    endpoint: str | None = None


class SoftBindingQueryResult(CamelModel):
    matches: list[Match] = Field(default_factory=list)


class MerkleCheckpoint(CamelModel):
    """A signed tree head, written to B2 under Object Lock for tamper-evidence."""

    epoch: int
    tree_size: int
    root_hash: str
    signed_at: str
    signature_b64: str


class AlgorithmEntry(CamelModel):
    """One advertised soft-binding algorithm (the C2PA SBR softBindingAlgList entry shape)."""

    alg: str


class SupportedAlgorithms(CamelModel):
    """Advertised at /services/supportedAlgorithms. PDQ is deliberately absent (internal only).

    The C2PA SBR spec shape is arrays of objects with an `alg` field, not bare strings.
    """

    watermarks: list[AlgorithmEntry] = Field(
        default_factory=lambda: [AlgorithmEntry(alg=ALG_TRUSTMARK_P)]
    )
    fingerprints: list[AlgorithmEntry] = Field(default_factory=list)
    # Configured federation peers: other SBR resolvers this node forwards a binding query to on a
    # local miss, so recovery is an open, vendor-neutral network rather than a single repository.
    peers: list[str] = Field(default_factory=list)
