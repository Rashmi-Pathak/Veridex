"""Ed25519 / COSE_Sign1 signing of the canonical manifest.

C2PA supports EdDSA (Ed25519). We build the COSE_Sign1 structure directly (RFC 8152) with cbor2 +
cryptography rather than pull a COSE library: the structure is small and fully under our control, so
the signed bytes and the verify path agree by construction. The payload is the manifest's canonical
JSON, the same bytes that anchor the canonical hash and the Merkle leaf.
"""

from __future__ import annotations

import cbor2
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .models import Manifest, canonical_json

COSE_ALG_EDDSA = -8  # COSE algorithm id for EdDSA
COSE_HEADER_ALG = 1  # COSE header label for "alg"
COSE_SIGN1_TAG = 18  # CBOR tag for COSE_Sign1


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def private_key_bytes(priv: Ed25519PrivateKey) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )


def load_private_key(raw: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(raw)


def public_key_bytes(pub: Ed25519PublicKey) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def load_public_key(raw: bytes) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(raw)


def _sig_structure(protected: bytes, payload: bytes) -> bytes:
    # The COSE Sig_structure that is actually signed (context, protected, external_aad, payload).
    return cbor2.dumps(["Signature1", protected, b"", payload])


def sign_cose_sign1(payload: bytes, priv: Ed25519PrivateKey) -> bytes:
    protected = cbor2.dumps({COSE_HEADER_ALG: COSE_ALG_EDDSA})
    signature = priv.sign(_sig_structure(protected, payload))
    return cbor2.dumps(cbor2.CBORTag(COSE_SIGN1_TAG, [protected, {}, payload, signature]))


def verify_cose_sign1(cose_bytes: bytes, pub: Ed25519PublicKey) -> bytes:
    """Return the payload if the signature is valid; raise InvalidSignature otherwise.

    Every failure mode for adversary-controlled bytes (malformed CBOR, wrong structure, non-bytes
    fields, a bad signature) collapses to InvalidSignature, so callers verify with a single narrow
    except and a public endpoint never 500s on crafted input. Caller bugs still propagate.
    """
    try:
        obj = cbor2.loads(cose_bytes)
    except cbor2.CBORDecodeError as exc:
        raise InvalidSignature("malformed CBOR") from exc
    seq = obj.value if isinstance(obj, cbor2.CBORTag) else obj
    arr = list(seq) if isinstance(seq, (list, tuple)) else []
    if len(arr) != 4:
        raise InvalidSignature("not a COSE_Sign1 structure")
    protected, _unprotected, payload, signature = arr
    if not all(isinstance(x, (bytes, bytearray)) for x in (protected, payload, signature)):
        raise InvalidSignature("COSE_Sign1 fields must be byte strings")
    pub.verify(bytes(signature), _sig_structure(bytes(protected), bytes(payload)))
    return bytes(payload)


def sign_manifest(manifest: Manifest, priv: Ed25519PrivateKey) -> bytes:
    """Sign the manifest's canonical payload. Personal provenance is excluded by canonical_payload,
    so a redacted manifest verifies against the same signature."""
    return sign_cose_sign1(canonical_json(manifest.canonical_payload()), priv)


def verify_manifest(cose_bytes: bytes, manifest: Manifest, pub: Ed25519PublicKey) -> bool:
    """True iff the signature is valid AND covers this manifest's canonical payload."""
    try:
        payload = verify_cose_sign1(cose_bytes, pub)
    except InvalidSignature:
        # verify_cose_sign1 already collapses malformed/adversarial input to InvalidSignature, so
        # this narrow catch is sufficient and does not mask caller bugs.
        return False
    return payload == canonical_json(manifest.canonical_payload())
