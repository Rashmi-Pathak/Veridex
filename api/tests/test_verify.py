"""Live tamper-evidence. /demo/signed-manifest serves the primary demo manifest + its COSE signature
(signed with the server's checkpoint key) + the public key; /verify re-verifies a possibly-edited
manifest against that signature, so changing any signed field (asset hash, model, id, timestamp)
visibly fails. This is the on-camera "tamper it and the signature breaks" beat."""

from __future__ import annotations

import copy

import httpx
from httpx import ASGITransport

from veridex_api.main import app


async def test_signed_manifest_verifies_then_tamper_then_garbage() -> None:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sm = await c.get("/demo/signed-manifest")
        assert sm.status_code == 200
        body = sm.json()
        manifest = body["manifest"]
        sig = body["signatureB64"]
        assert len(body["publicKeyHex"]) == 64
        assert manifest["systemProvenance"]["model"] == "seedream-5.0-lite"

        # the untouched, signed manifest verifies
        ok = await c.post("/verify", json={"manifest": manifest, "signatureB64": sig})
        assert ok.status_code == 200
        assert ok.json()["signatureValid"] is True

        # tampering a SIGNED field (the claimed model) breaks the signature
        tampered = copy.deepcopy(manifest)
        tampered["systemProvenance"] = {"model": "totally-different-model"}
        bad = await c.post("/verify", json={"manifest": tampered, "signatureB64": sig})
        assert bad.status_code == 200
        assert bad.json()["signatureValid"] is False

        # tampering the asset hash also breaks it
        tampered2 = copy.deepcopy(manifest)
        tampered2["assetSha256"] = "0" * 64
        bad2 = await c.post("/verify", json={"manifest": tampered2, "signatureB64": sig})
        assert bad2.json()["signatureValid"] is False

        # a garbage signature is a clean False, not a 500
        junk = await c.post("/verify", json={"manifest": manifest, "signatureB64": "not base64 !!"})
        assert junk.status_code == 200
        assert junk.json()["signatureValid"] is False
