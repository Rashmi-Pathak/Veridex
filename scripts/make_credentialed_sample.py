"""Regenerate web/public/credentialed-sample.jpg: a real C2PA-credentialed JPEG, signed with the
ES256 test certificate, for the front-end Content Credentials display.

The signed image is committed; the signing key is NOT (it lives in the gitignored
research/c2pa-test-certs/). Run from the repo root:
`uv run python scripts/make_credentialed_sample.py`.
The test cert yields a "Valid" signature without a trust list, and the green "Trusted" state when
validated against the C2PA conformance test trust list (the test certificate is marked FOR TESTING
ONLY; production validates against the C2PA production trust list). The UI shows both honestly.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from veridex_api.demo import _demo_image
from veridex_provenance.claim import (
    build_manifest_def,
    conformance_trust_anchors,
    conformance_trust_config,
    make_es256_signer,
    read_claim,
    sign_claim,
)
from veridex_provenance.models import Manifest

CERTS = Path("research/c2pa-test-certs")
OUT = Path("web/public/credentialed-sample.jpg")


def main() -> None:
    buf = io.BytesIO()
    _demo_image(7).convert("RGB").save(buf, "JPEG", quality=90)
    jpeg = buf.getvalue()

    manifest = Manifest(
        manifest_id="urn:c2pa:demo-credentialed-0000-0000-000000000003",
        asset_sha256=hashlib.sha256(jpeg).hexdigest(),
        created_at="2026-06-27T00:00:00Z",
        system_provenance={"model": "rooted-demo-fixture", "note": "C2PA-credentialed demo asset"},
    )
    signer = make_es256_signer(
        (CERTS / "es256_certs.pem").read_text(),
        (CERTS / "es256_private.key").read_bytes(),
    )
    # This demo asset is a procedurally drawn image, not output of a generative model, so it is
    # explicitly NOT marked AI-generated (no digitalSourceType): the credential stays honest.
    signed = sign_claim(
        signer,
        jpeg,
        build_manifest_def(manifest, "DEMO", "image/jpeg", ai_generated=False),
        "image/jpeg",
    )

    _mj, valid = read_claim(signed, fmt="image/jpeg")
    _mj2, trusted = read_claim(
        signed,
        fmt="image/jpeg",
        trust_anchors=conformance_trust_anchors(),
        trust_config=conformance_trust_config(),
    )
    print(
        f"validation_state: {valid}; with the conformance trust list: {trusted}; "
        f"signed bytes: {len(signed)}"
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(signed)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
