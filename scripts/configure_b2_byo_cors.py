"""One-shot: configure the Backblaze B2 CORS rule that lets the browser PUT a BYO upload DIRECT to
the dev bucket via a presigned S3 URL (veridex_api.byo). Reads B2 credentials from .env (no secret
literal in this file), in the style of configure_b2_event_rule.py.

B2 CORS rules are bucket-scoped (there is no per-prefix scoping), so the rule is scoped by origin +
method instead: only the production web origin and localhost may PUT, only the content-type header
is allowed, and the byo/ key shape is enforced server-side by the API (server-generated keys only).

Safety: dry-run by default (prints the exact rule and the resulting rule set, mutates nothing);
pass --apply to write. Idempotent: an identical existing rule is a no-op, a stale same-name rule is
replaced, every other rule is preserved. It refuses to touch the Object-Lock bucket
(B2_BUCKET_LOCKED) no matter what the env says.

Run: uv run python scripts/configure_b2_byo_cors.py           # dry run (default)
     uv run python scripts/configure_b2_byo_cors.py --apply   # actually write the rule
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import b2sdk.v2 as v2

_ENV = Path(__file__).resolve().parents[1] / ".env"
_RULE_NAME = "rooted-byo-upload"
_ALLOWED_ORIGINS = [
    "https://veridex-web-phi.vercel.app",
    "http://localhost:3000",
]


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.split(" #", 1)[0].strip().strip('"').strip("'")
    return out


def _rule() -> dict[str, object]:
    return {
        "corsRuleName": _RULE_NAME,
        "allowedOrigins": list(_ALLOWED_ORIGINS),
        # s3_put covers the presigned S3 PUT (and its preflight) on the S3-compatible endpoint;
        # s3_head lets the browser confirm the upload landed if it wants to.
        "allowedOperations": ["s3_put", "s3_head"],
        "allowedHeaders": ["content-type"],
        "maxAgeSeconds": 3600,
    }


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

    desired = _rule()
    existing: list[dict[str, object]] = list(bucket.cors_rules or [])
    kept = [r for r in existing if r.get("corsRuleName") != _RULE_NAME]
    current = next((r for r in existing if r.get("corsRuleName") == _RULE_NAME), None)

    print(f"bucket: {bucket_name}")
    print(f"existing CORS rules: {len(existing)} (ours present: {current is not None})")
    if current == desired:
        print("OK: the rule is already in place and identical; nothing to do")
        return
    new_rules = [*kept, desired]
    print("would write" if not apply else "writing", "this CORS rule set:")
    print(json.dumps(new_rules, indent=2))
    if not apply:
        print("dry run (default): nothing was changed. Re-run with --apply to write it.")
        return
    bucket.update(cors_rules=new_rules)
    fresh = bucket.get_fresh_state()
    print(f"OK: CORS rules set on {bucket_name}; bucket now reports:")
    print(json.dumps(list(fresh.cors_rules or []), indent=2))


if __name__ == "__main__":
    main()
