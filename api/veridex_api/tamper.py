"""Tamper-diff forensics: when a manifest is altered, recover the AUTHENTIC one from the registry
and show WHICH signed field changed, not just a binary pass/fail.

The COSE signature (over the canonical payload: manifest id, asset sha256, created-at, system
provenance) proves tamper; the diff makes it forensic: the registry's authentic value next to the
submitted (altered) value, per signed field. Degrades honestly (falls back to the demo manifest if
the registry has no entry), never 500.
"""

from __future__ import annotations

import base64
import binascii
import logging

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from veridex_provenance.models import CamelModel, Manifest, canonical_json
from veridex_provenance.signing import verify_manifest

router = APIRouter()
logger = logging.getLogger(__name__)


class TamperDiffRequest(CamelModel):
    manifest: Manifest
    signature_b64: str


class FieldDiff(CamelModel):
    field: str
    authentic: str
    submitted: str
    changed: bool


class TamperDiffResponse(CamelModel):
    signature_valid: bool
    tampered: bool
    authentic_source: str  # "registry" | "demo"
    fields: list[FieldDiff]


def _signed_fields(m: Manifest) -> dict[str, tuple[str, str]]:
    """The fields the signature covers (the canonical payload), flattened as {field: (display,
    compare)}. The compare value is canonical JSON for system_provenance values, so a typed change
    (1 vs "1") or a key-order shuffle is caught the way the signature covers it, not lost to str().
    The top-level fields are already strings."""
    fields: dict[str, tuple[str, str]] = {
        "manifest_id": (m.manifest_id, m.manifest_id),
        "asset_sha256": (m.asset_sha256, m.asset_sha256),
        "created_at": (m.created_at, m.created_at),
    }
    for key, value in (m.system_provenance or {}).items():
        fields[f"system_provenance.{key}"] = (str(value), canonical_json(value).decode("utf-8"))
    return fields


@router.post("/demo/tamper-diff", response_model=TamperDiffResponse, include_in_schema=False)
async def tamper_diff(req: TamperDiffRequest) -> TamperDiffResponse:
    """Check the submitted manifest's signature, recover the authentic manifest from the registry,
    and return a field-level diff over the signed fields. tampered is true when the signature does
    not cover the submission or any signed field differs from the authentic record."""
    from veridex_api import sbr
    from veridex_api.demo import primary_manifest

    submitted = req.manifest
    try:
        cose = base64.b64decode(req.signature_b64, validate=True)
        signature_valid = await run_in_threadpool(
            verify_manifest, cose, submitted, sbr.signing_public_key()
        )
    except (binascii.Error, ValueError):
        signature_valid = False

    try:
        authentic = await run_in_threadpool(sbr.get_resolver().get_manifest, submitted.manifest_id)
    except Exception as exc:  # noqa: BLE001 - a registry hiccup must not 500 the demo surface
        logger.warning("tamper-diff registry lookup failed: %s", exc)
        authentic = None
    source = "registry"
    if authentic is None:
        authentic = primary_manifest()
        source = "demo"

    # Diff over the DISCLOSED (redacted) signed fields on both sides, so a legacy authentic that
    # carries a prompt in system_provenance and a current manifest that keeps the prompt in personal
    # provenance are compared on the same basis (the prompt, personal either way, is never a diffed
    # field). The signature check above still covers the FULL canonical payload, so any real tamper
    # of a signed field is caught there regardless.
    a = _signed_fields(authentic.redacted())
    s = _signed_fields(submitted.redacted())
    fields = []
    for key in sorted(set(a) | set(s)):
        a_val = a.get(key)
        s_val = s.get(key)
        fields.append(
            FieldDiff(
                field=key,
                authentic=a_val[0] if a_val else "(absent)",
                submitted=s_val[0] if s_val else "(absent)",
                changed=a_val is None or s_val is None or a_val[1] != s_val[1],
            )
        )
    tampered = (not signature_valid) or any(f.changed for f in fields)
    return TamperDiffResponse(
        signature_valid=signature_valid,
        tampered=tampered,
        authentic_source=source,
        fields=fields,
    )
