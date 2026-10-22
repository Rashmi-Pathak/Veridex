"""C2PA claim wrapping: turn a Rooted manifest into a real, signed Content Credential.

We sign through c2pa-python's from_callback path so the signing key stays in our control and no
timestamp authority is required. ES256 is the most broadly supported C2PA algorithm (c2pa-rs
validates the signing cert against its profile at sign time, so a malformed self-signed cert is
rejected; a conformant test or self-signed chain validates as "Valid"). "Valid" means the signature
checks out, NOT the green "Trusted" state, which requires a Conformance-Program CA. We surface that
distinction honestly rather than hide it.
"""

from __future__ import annotations

import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import c2pa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from .models import ALG_TRUSTMARK_P, Manifest

# The C2PA standard soft-binding assertion label (c2pa-rs labels::SOFT_BINDING, C2PA spec). A
# third-party reader (c2pa-web, Adobe Verify, the CAI inspector) recognizes this assertion; a
# vendor-custom label would be ignored as opaque. The payload still references the registered
# TrustMark variant P algorithm, so only the label and shape change, not the watermark it points to.
SOFT_BINDING_LABEL = "c2pa.soft-binding"
ACTIONS_LABEL = "c2pa.actions"

# IPTC DigitalSourceType for media produced by a generative AI model, the full IRI from the IPTC
# digitalsourcetype vocabulary. Added to the c2pa.created action only for genuinely AI-generated
# assets, so the credential says "AI-generated" exactly when that is true.
DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA = (
    "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
)

# system_provenance.model values that name no concrete generator, so the asset is not claimed as AI.
_NON_GENERATOR_MODELS = frozenset({"", "unknown", "none", "n/a", "na"})


def _is_ai_generated(system_provenance: dict[str, Any]) -> bool:
    """True when system provenance names a concrete generative model, so digitalSourceType is honest
    to emit. A missing, empty, or placeholder model (e.g. "unknown") is not claimed as AI."""
    model = system_provenance.get("model")
    return isinstance(model, str) and model.strip().lower() not in _NON_GENERATOR_MODELS


def make_es256_signer(cert_chain_pem: str, private_key_pem: bytes) -> c2pa.Signer:
    """Build a c2pa Signer that signs with the given ES256 (P-256) key, no timestamp authority."""
    key = load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("ES256 signer requires an EC P-256 private key")

    def sign_cb(data: bytes) -> bytes:
        der = key.sign(data, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")  # C2PA wants raw r||s, not DER

    return c2pa.Signer.from_callback(
        sign_cb, c2pa.C2paSigningAlg.ES256, certs=cert_chain_pem, tsa_url=None
    )


def build_manifest_def(
    manifest: Manifest,
    watermark_id: str,
    fmt: str = "image/jpeg",
    *,
    ai_generated: bool | None = None,
) -> dict[str, Any]:
    """The C2PA manifest definition: the standard soft-binding pointer plus system provenance.

    The soft binding uses the C2PA spec assertion (c2pa.soft-binding) with the standard
    {alg, blocks:[{scope, value}]} shape, so a third-party reader recognizes it; the payload still
    references the registered TrustMark variant P algorithm, and the watermark id is the block value
    the SBR API later resolves.

    digitalSourceType (IPTC trainedAlgorithmicMedia) is added to the c2pa.created action when the
    asset is AI-generated, so the credential states that honestly. ai_generated defaults to
    inferring it from system_provenance (a concrete model name); pass it explicitly to mark a known
    non-AI fixture (ai_generated=False) regardless of the model field.
    """
    if ai_generated is None:
        ai_generated = _is_ai_generated(manifest.system_provenance)
    created: dict[str, Any] = {"action": "c2pa.created"}
    if ai_generated:
        created["digitalSourceType"] = DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA
    return {
        "claim_generator": "rooted/0.1.0",
        "claim_generator_info": [{"name": "rooted", "version": "0.1.0"}],
        "format": fmt,
        "title": manifest.manifest_id,
        "assertions": [
            {"label": ACTIONS_LABEL, "data": {"actions": [created]}},
            {
                "label": SOFT_BINDING_LABEL,
                "data": {
                    "alg": ALG_TRUSTMARK_P,
                    "blocks": [{"scope": {}, "value": watermark_id}],
                },
            },
            {
                "label": "com.rooted.provenance",
                "data": {
                    "manifest_id": manifest.manifest_id,
                    "asset_sha256": manifest.asset_sha256,
                    "system_provenance": manifest.system_provenance,
                },
            },
        ],
    }


def sign_claim(
    signer: c2pa.Signer, image_bytes: bytes, manifest_def: dict[str, Any], fmt: str = "image/jpeg"
) -> bytes:
    """Embed and sign the C2PA manifest into the asset; return the signed asset bytes."""
    builder = c2pa.Builder(manifest_def)
    dest = io.BytesIO()
    builder.sign(signer, fmt, io.BytesIO(image_bytes), dest)
    return dest.getvalue()


# The C2PA conformance test trust list. anchors.pem + store.cfg are the C2PA project's PUBLIC test
# fixtures (the certs are marked FOR TESTING_ONLY): the test root CAs and the allowed signing EKUs.
# A manifest signed with the matching C2PA test certificate validates against these as the green
# "Trusted" state. A production deployment uses the C2PA production trust list
# (contentcredentials.org) instead; these demonstrate the trusted path honestly, not a production
# trust claim.
_CONFORMANCE_DIR = Path(__file__).resolve().parent / "conformance"


@lru_cache(maxsize=1)
def conformance_trust_anchors() -> str:
    """The C2PA conformance test trust anchors (root CA bundle), as PEM text."""
    return (_CONFORMANCE_DIR / "anchors.pem").read_text()


@lru_cache(maxsize=1)
def conformance_trust_config() -> str:
    """The C2PA conformance trust config: the allowed signing-certificate EKUs."""
    return (_CONFORMANCE_DIR / "store.cfg").read_text()


def read_claim(
    signed_bytes: bytes,
    fmt: str = "image/jpeg",
    trust_anchors: str | None = None,
    trust_config: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Read the embedded C2PA manifest back; return (manifest_json, validation_state).

    With trust_anchors supplied, validation runs against that trust list: a manifest whose signing
    cert chains to an anchor with an allowed EKU (per trust_config) validates as "Trusted" (the
    green state), not just "Valid". Without anchors the issuer is not checked, so a valid signature
    reads "Valid". Pass conformance_trust_anchors()/conformance_trust_config() to validate against
    the C2PA conformance test trust list.
    """
    if trust_anchors is None:
        reader = c2pa.Reader(fmt, io.BytesIO(signed_bytes))
        return json.loads(reader.json()), reader.get_validation_state()

    trust: dict[str, str] = {"trust_anchors": trust_anchors}
    if trust_config is not None:
        trust["trust_config"] = trust_config
    settings = c2pa.Settings.from_dict({"verify": {"verify_trust": True}, "trust": trust})
    with c2pa.Context(settings) as ctx:
        with c2pa.Reader(fmt, io.BytesIO(signed_bytes), context=ctx) as reader:
            return json.loads(reader.json()), reader.get_validation_state()
