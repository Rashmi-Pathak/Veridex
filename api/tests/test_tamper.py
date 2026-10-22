"""Tamper-diff forensics: /demo/tamper-diff checks the signature, recovers the authentic manifest,
and returns a field-level diff. An untampered manifest is clean; an altered signed field is flagged
with the authentic value next to the submitted one."""

from __future__ import annotations

from typing import Any, cast

import httpx
from httpx import ASGITransport
from PIL import Image

from veridex_api.main import app


async def _signed(c: httpx.AsyncClient) -> dict[str, Any]:
    r = await c.get("/demo/signed-manifest")
    assert r.status_code == 200, r.text
    return cast("dict[str, Any]", r.json())


async def test_tamper_diff_clean_for_authentic_manifest() -> None:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        signed = await _signed(c)
        r = await c.post(
            "/demo/tamper-diff",
            json={"manifest": signed["manifest"], "signatureB64": signed["signatureB64"]},
        )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["signatureValid"] is True
    assert b["tampered"] is False
    assert all(not f["changed"] for f in b["fields"])


async def test_tamper_diff_clean_when_registry_authentic_is_legacy_shaped() -> None:
    # The live case (merge != live): the registry holds a LEGACY manifest with the prompt in
    # system_provenance, while /demo/signed-manifest serves the current shape (prompt in personal).
    # Comparing on the DISCLOSED (redacted) signed fields, the unedited manifest is NOT tampered.
    from veridex_api import sbr
    from veridex_api.demo import primary_manifest
    from veridex_provenance.merkle import TransparencyLog
    from veridex_provenance.resolver import InMemoryIndex, Resolver
    from veridex_provenance.watermark import FakeWatermarker

    resolver = Resolver(InMemoryIndex(), FakeWatermarker())
    sbr.set_resolver(resolver)
    sbr.set_log(TransparencyLog())
    try:
        current = primary_manifest()
        legacy = current.model_copy(
            update={
                "system_provenance": {
                    **current.system_provenance,
                    "prompt": current.personal_provenance["prompt"],
                },
                "personal_provenance": {},
            }
        )
        resolver.register(legacy, Image.new("RGB", (64, 64)), "DEMO")
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            signed = await _signed(c)
            r = await c.post(
                "/demo/tamper-diff",
                json={"manifest": signed["manifest"], "signatureB64": signed["signatureB64"]},
            )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["authenticSource"] == "registry"  # it used the stored legacy authentic
        assert b["signatureValid"] is True
        assert b["tampered"] is False
        assert all(not f["changed"] for f in b["fields"])
    finally:
        sbr.set_resolver(None)
        sbr.set_log(None)


async def test_tamper_diff_flags_the_changed_field() -> None:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        signed = await _signed(c)
        manifest = dict(signed["manifest"])
        manifest["systemProvenance"] = {
            **manifest["systemProvenance"],
            "model": "evil-swapped-model",
        }
        r = await c.post(
            "/demo/tamper-diff",
            json={"manifest": manifest, "signatureB64": signed["signatureB64"]},
        )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["signatureValid"] is False  # the signature no longer covers the altered manifest
    assert b["tampered"] is True
    model = next(f for f in b["fields"] if f["field"] == "system_provenance.model")
    assert model["changed"] is True
    assert model["submitted"] == "evil-swapped-model"
    assert model["authentic"] != "evil-swapped-model"
    # untouched signed fields are not flagged
    assert any(f["field"] == "asset_sha256" and not f["changed"] for f in b["fields"])
