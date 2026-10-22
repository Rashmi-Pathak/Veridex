"""One-shot: set default server-side encryption (SSE-B2, AES256) on the dev bucket, in the style of
configure_b2_byo_cors.py. Reads B2 credentials from .env (no secret literal in this file).

SSE-B2 encrypts objects at rest with a B2-managed AES-256 key. A bucket default applies to NEW
uploads only: objects already in the bucket stay as written (B2 does not retro-encrypt). Reads,
downloads, and the presigned S3 PUT flow are unchanged; B2 decrypts transparently on read.

The current setting is read live from the bucket (b2sdk exposes it as an EncryptionSetting whose
mode is UNKNOWN when the authorized key lacks readBucketEncryption; that is printed honestly, and
applying is still safe because setting SSE-B2 is idempotent).

Safety: dry-run by default (prints current vs target, mutates nothing); pass --apply to write. It
refuses to touch the Object-Lock bucket (B2_BUCKET_LOCKED) no matter what the env says.

Run: uv run python scripts/configure_b2_sse.py           # dry run (default)
     uv run python scripts/configure_b2_sse.py --apply   # actually set SSE-B2
"""

from __future__ import annotations

import sys
from pathlib import Path

import b2sdk.v2 as v2

_ENV = Path(__file__).resolve().parents[1] / ".env"

TARGET_MODE = "SSE-B2"
TARGET_ALGORITHM = "AES256"


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.split(" #", 1)[0].strip().strip('"').strip("'")
    return out


def plan(current_mode: str | None, current_algorithm: str | None) -> tuple[bool, str]:
    """Pure planning: (whether an update is needed, a one-line description). current_mode None
    means the bucket reported the setting as unknown to this key (readBucketEncryption missing);
    the target is still SSE-B2 and applying is idempotent, so we plan the write and say why."""
    if current_mode == TARGET_MODE and current_algorithm == TARGET_ALGORITHM:
        return False, f"default encryption is already {TARGET_MODE} ({TARGET_ALGORITHM})"
    if current_mode is None:
        return True, (
            "current default encryption is UNKNOWN to this key (readBucketEncryption missing); "
            f"target is {TARGET_MODE} ({TARGET_ALGORITHM}); applying is idempotent"
        )
    return True, (
        f"current default encryption is {current_mode!r}; "
        f"target is {TARGET_MODE} ({TARGET_ALGORITHM})"
    )


def _current(bucket: object) -> tuple[str | None, str | None]:
    """(mode, algorithm) of the bucket's default encryption as b2sdk reports it. The UNKNOWN mode's
    enum value is None, which is exactly the honest 'this key cannot read it' signal."""
    enc = getattr(bucket, "default_server_side_encryption", None)
    mode = getattr(getattr(enc, "mode", None), "value", None)
    algorithm = getattr(getattr(enc, "algorithm", None), "value", None)
    return mode, algorithm


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    env = _env()
    bucket_name = env["B2_BUCKET_DEV"]
    locked_name = env.get("B2_BUCKET_LOCKED", "rooted-locked")
    if bucket_name == locked_name or bucket_name == "rooted-locked":
        raise SystemExit(
            f"refusing to touch {bucket_name!r}: it is (or is named like) the Object-Lock bucket"
        )

    api = v2.B2Api(v2.InMemoryAccountInfo())
    api.authorize_account("production", env["B2_KEY_ID"], env["B2_APP_KEY"])
    bucket = api.get_bucket_by_name(bucket_name)

    mode, algorithm = _current(bucket)
    print(f"bucket: {bucket_name}")
    print(f"current default encryption: mode={mode!r} algorithm={algorithm!r}")
    print(f"target  default encryption: mode={TARGET_MODE!r} algorithm={TARGET_ALGORITHM!r}")
    needed, description = plan(mode, algorithm)
    print(description)
    if not needed:
        print("OK: nothing to do")
        return
    print("note: the default applies to NEW uploads only; existing objects stay as written.")
    if not apply:
        print("dry run (default): nothing was changed. Re-run with --apply to set SSE-B2.")
        return
    bucket.update(
        default_server_side_encryption=v2.EncryptionSetting(
            mode=v2.EncryptionMode.SSE_B2, algorithm=v2.EncryptionAlgorithm.AES256
        )
    )
    fresh_mode, fresh_algorithm = _current(bucket.get_fresh_state())
    print(
        f"OK: default encryption set on {bucket_name}; bucket now reports "
        f"mode={fresh_mode!r} algorithm={fresh_algorithm!r}"
    )


if __name__ == "__main__":
    main()
