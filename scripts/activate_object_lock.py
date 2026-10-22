"""One-shot: prove (and enable) Backblaze B2 Object Lock for the Merkle checkpoint seal.

Run this yourself so your B2 credentials load from your shell / .env and are never exposed to anyone
else:

    uv run python scripts/activate_object_lock.py rooted-locked

What it does, in order, printing a clear PASS or FAIL at each step:
  1. Authorizes B2 and prints the key's capabilities (not the secret) so you can confirm it has
     writeFileRetentions + readFileRetentions (needed for Object Lock).
  2. Gets or creates the named bucket with Object Lock enabled (fileLock can only be turned on, and
     for a brand-new bucket it must be set at creation).
  3. Writes a tiny probe object under a SHORT compliance retention (default 1 day) so it auto-frees.
  4. Reads the retention back from B2 and asserts it is compliance with a future retain-until.
  5. Attempts to delete the retained probe and asserts B2 refuses it (the WORM guarantee).

If every step passes, it prints the bucket name to set as B2_BUCKET_LOCKED on the veridex-api Render
service. Nothing here touches the rooted-dev iteration bucket. The probe is short-lived.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROBE_KEY = "merkle/checkpoints/_activation_probe.json"


def _load_env() -> None:
    """Load B2_* from the repo-root .env into os.environ if not already set, so the script works
    whether the keys are exported or only in .env. Only B2_* keys are read; nothing is printed."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("B2_") and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def main() -> int:
    _load_env()
    key_id = os.environ.get("B2_KEY_ID")
    app_key = os.environ.get("B2_APP_KEY")
    bucket_name = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("B2_BUCKET_LOCKED")
    retain_days = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    if not (key_id and app_key):
        print("FAIL: B2_KEY_ID / B2_APP_KEY not found in the environment or .env")
        return 1
    if not bucket_name:
        print(
            "FAIL: pass a bucket name, e.g. `python scripts/activate_object_lock.py rooted-locked`"
        )
        return 1

    from b2sdk.v2 import B2Api, FileRetentionSetting, InMemoryAccountInfo, RetentionMode
    from b2sdk.v2.exception import B2Error

    api = B2Api(InMemoryAccountInfo())
    api.authorize_account("production", key_id, app_key)

    allowed = api.account_info.get_allowed()
    caps = allowed.get("capabilities", [])
    scoped = allowed.get("bucketName")
    needed = {"writeFileRetentions", "readFileRetentions", "writeFiles", "readFiles"}
    print(f"key capabilities present: {sorted(c for c in needed if c in caps)}")
    print(f"key capabilities MISSING: {sorted(needed - set(caps))}")
    if scoped:
        print(f"NOTE: this key is restricted to bucket '{scoped}'. It can only act on that bucket.")
    if not {"writeFileRetentions", "readFileRetentions"} <= set(caps):
        print(
            "FAIL: the key lacks writeFileRetentions/readFileRetentions. Create a new B2 "
            "application key with those caps (and access to the locked bucket), then re-run."
        )
        return 1

    # Step 2: get or create the bucket with Object Lock enabled.
    try:
        bucket = api.get_bucket_by_name(bucket_name)
        locked = getattr(bucket, "is_file_lock_enabled", None)
        print(f"bucket '{bucket_name}' exists (fileLockEnabled={locked})")
        if locked is False:
            print("enabling Object Lock on the existing bucket...")
            bucket.update(is_file_lock_enabled=True)
    except B2Error:
        print(f"creating bucket '{bucket_name}' with Object Lock enabled...")
        bucket = api.create_bucket(bucket_name, "allPrivate", is_file_lock_enabled=True)
    print("PASS: bucket ready with Object Lock")

    # Step 3: write a short-retention probe.
    until_ms = int((time.time() + retain_days * 86400) * 1000)
    bucket.upload_bytes(
        b'{"probe":"object-lock-activation"}',
        PROBE_KEY,
        file_retention=FileRetentionSetting(RetentionMode.COMPLIANCE, until_ms),
    )
    print(f"PASS: wrote probe under compliance retention for {retain_days} day(s)")

    # Step 4: read the retention back from B2.
    info = bucket.get_file_info_by_name(PROBE_KEY)
    fr = getattr(info, "file_retention", None)
    mode = getattr(getattr(fr, "mode", None), "value", None)
    until = getattr(fr, "retain_until", None)
    print(f"read-back retention: mode={mode} retain_until_ms={until}")
    if mode != "compliance" or not until or until <= int(time.time() * 1000):
        print("FAIL: the probe did not come back under an active compliance retention")
        return 1
    print("PASS: B2 reports the probe as compliance-retained with a future retain-until")

    # Step 5: prove the delete is refused.
    try:
        bucket.delete_file_version(info.id_, PROBE_KEY)
        print("FAIL: B2 allowed deleting a compliance-retained object (lock not enforced)")
        return 1
    except B2Error as exc:
        print(f"PASS: B2 refused the delete (WORM enforced): {type(exc).__name__}")

    print()
    print("ALL CHECKS PASSED. Backblaze B2 Object Lock works with this key + bucket.")
    print(f"Set this on the veridex-api Render service:  B2_BUCKET_LOCKED={bucket_name}")
    print("Then redeploy; the startup seal will write a real immutable checkpoint to B2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
