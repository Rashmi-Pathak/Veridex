"""One-off builder for the Genblaze -> B2 dual-axis demo fixtures (run once; commit the outputs).

Runs a REAL Genblaze Pipeline generation (GMI Cloud seedream), writes the run to Backblaze B2 via
Genblaze's OWN ObjectStorageSink (coupling the B2 + Genblaze axes: the generator's SDK persists its
provenance to Backblaze), and captures the native hash-verified manifest + the generated asset as
committed fixtures. The /demo/genblaze-manifest endpoint reads these to show the Genblaze integrity
manifest reconciled with Rooted's signed C2PA manifest (Genblaze proves integrity; Rooted adds the
COSE signature, the C2PA claim, recovery, and the transparency proof).

Run: uv run python api/veridex_api/make_genblaze_b2_sample.py  (needs GMI + B2 creds in .env).
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from genblaze_core import Modality, Pipeline
from genblaze_core.storage.sink import ObjectStorageSink
from genblaze_gmicloud import GMICloudImageProvider
from genblaze_s3 import S3StorageBackend

_ASSETS = Path(__file__).parent / "assets"
_PROMPT = (
    "a single rooted oak tree on a floating island in a deep blue starfield, "
    "cinematic, photorealistic"
)


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (Path(__file__).resolve().parents[2] / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        # Strip only a " #" inline comment so a value containing '#' (e.g. a password) is preserved.
        env[k.strip()] = v.split(" #", 1)[0].strip().strip('"').strip("'")
    return env


def main() -> None:
    env = _env()
    result = (
        Pipeline("rooted-genblaze-b2")
        .step(
            GMICloudImageProvider(api_key=env["GMI_CLOUD_API_KEY"]),
            model=env.get("VERIDEX_GMI_MODEL") or "seedream-5.0-lite",
            prompt=_PROMPT,
            modality=Modality.IMAGE,
        )
        .run(raise_on_failure=True, timeout=120)
    )
    manifest = result.manifest
    assert manifest.verify_hash(), "Genblaze manifest failed canonical_hash verification"

    asset = result.run.steps[0].assets[0]
    data = urllib.request.urlopen(asset.url, timeout=60).read()  # noqa: S310 - trusted GMI asset URL
    sha = hashlib.sha256(data).hexdigest()

    # Write the run to B2 via Genblaze's OWN ObjectStorageSink (the dual-axis: Genblaze persists its
    # asset + manifest to Backblaze through its native S3 backend).
    backend = S3StorageBackend.for_backblaze(
        bucket=env["B2_BUCKET_DEV"],
        region="us-east-005",
        key_id=env["B2_KEY_ID"],
        app_key=env["B2_APP_KEY"],
    )
    ObjectStorageSink(backend).write_run(result.run, manifest)

    _ASSETS.mkdir(exist_ok=True)
    (_ASSETS / "genblaze-b2-asset.jpg").write_bytes(data)
    (_ASSETS / "genblaze-b2-manifest.json").write_text(manifest.model_dump_json(indent=2))

    print("OK")
    print("asset sha256:", sha)
    print("manifest output asset sha256:", asset.sha256)
    print("reconcile (sha == asset.sha256):", sha == asset.sha256)
    print("canonical_hash:", manifest.canonical_hash)
    print("run_id:", manifest.run.run_id)
    print("verify_hash:", manifest.verify_hash())


if __name__ == "__main__":
    main()
