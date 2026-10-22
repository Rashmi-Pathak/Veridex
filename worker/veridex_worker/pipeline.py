"""The ingest pipeline: generate -> watermark -> store -> sign -> index -> log.

This is the generation side of the loop. It produces a manifest, signs it, stores the asset
content-addressably on B2, indexes it for recovery, and appends it to the Merkle transparency log,
so the asset is recoverable even after its embedded credential is stripped. The recovery side is the
SBR API. Every dependency is a Protocol, so the fakes prove the loop and the real B2 / TrustMark /
Genblaze backends drop in unchanged.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.models import ALG_TRUSTMARK_P, Manifest, SoftBinding, canonical_json
from veridex_provenance.resolver import Resolver
from veridex_provenance.signing import sign_manifest
from veridex_provenance.watermark import Watermarker
from veridex_storage.storage import Storage, asset_key, manifest_key, signature_key

from .generator import Generator


@dataclass
class IngestResult:
    manifest: Manifest
    cose_signature: bytes
    merkle_index: int
    credential_embedded: bool


class IngestPipeline:
    def __init__(
        self,
        generator: Generator,
        storage: Storage,
        watermarker: Watermarker,
        resolver: Resolver,
        log: TransparencyLog,
        signing_key: Ed25519PrivateKey,
        claim_signer: Any | None = None,
    ) -> None:
        self._gen = generator
        self._storage = storage
        self._wm = watermarker
        self._resolver = resolver
        self._log = log
        self._key = signing_key
        self._claim_signer = claim_signer  # a c2pa Signer; when set, embed a C2PA credential

    def run(self, prompt: str, watermark_id: str) -> IngestResult:
        gen = self._gen.generate(prompt)
        # the watermarked asset is what circulates and later gets stripped, so we hash, store and
        # index that one (not the pre-watermark original).
        watermarked = self._wm.encode(gen.image, watermark_id)
        buf = io.BytesIO()
        watermarked.save(buf, "JPEG", quality=90)  # JPEG so a C2PA credential can embed
        born = buf.getvalue()
        sha = hashlib.sha256(born).hexdigest()  # the pre-embed content hash (C2PA hard-binding ref)

        manifest = Manifest(
            manifest_id=f"urn:c2pa:{uuid4()}",
            asset_sha256=sha,
            created_at=datetime.now(UTC).isoformat(),
            system_provenance={"model": gen.model, "provider": gen.provider},
            personal_provenance={"prompt": prompt},
            soft_bindings=[SoftBinding(alg=ALG_TRUSTMARK_P, value=watermark_id)],
        )

        # The circulating asset carries an embedded C2PA credential when a claim signer is set;
        # that embedded manifest is what a screenshot strips and the watermark later recovers.
        circulating = born
        if self._claim_signer is not None:
            from veridex_provenance.claim import build_manifest_def, sign_claim

            circulating = sign_claim(
                self._claim_signer, born, build_manifest_def(manifest, watermark_id)
            )

        self._storage.put(asset_key(sha), circulating)
        self._storage.put(manifest_key(manifest.manifest_id), canonical_json(manifest.model_dump()))
        cose = sign_manifest(manifest, self._key)
        self._storage.put(signature_key(manifest.manifest_id), cose)
        self._resolver.register(manifest, watermarked, watermark_id)
        index = self._log.append(manifest.manifest_id, manifest.canonical_hash())
        return IngestResult(
            manifest=manifest,
            cose_signature=cose,
            merkle_index=index,
            credential_embedded=self._claim_signer is not None,
        )
