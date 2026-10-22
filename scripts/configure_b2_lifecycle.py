"""One-shot: configure Backblaze B2 lifecycle rules on the dev bucket, in the style of
configure_b2_byo_cors.py. Reads B2 credentials from .env (no secret literal in this file).

Managed rules (rooted-dev ONLY, matched by fileNamePrefix):
  byo/     hidden 1 day after upload, deleted 1 day after hiding. Judge uploads are transient
           carriers: the registered manifest, its PDQ fingerprint, and its transparency-log leaf
           persist in the registry, so recovery keeps working after B2 deletes the upload.
  ingest/  hidden 7 days after upload, deleted 1 day after hiding. Same persistence note: the
           event-ingested manifest and its proof outlive the dropped object.

B2 lifecycle semantics: daysFromUploadingToHiding hides a file N days after upload (it stops being
listed or served); daysFromHidingToDeleting deletes it N days after it was hidden. So byo/ objects
are fully gone in about 2 days and ingest/ objects in about 8.

Safety: dry-run by default (prints the current rules, the exact changes, and the full rule set that
would be written; mutates nothing); pass --apply to write. Idempotent: an identical managed rule is
a no-op, a stale managed rule is replaced, and every rule for a prefix we do not manage is
preserved. It refuses to touch the Object-Lock bucket (B2_BUCKET_LOCKED) no matter what the env
says (a lifecycle delete rule on the WORM audit bucket would be a contradiction in terms).

Run: uv run python scripts/configure_b2_lifecycle.py           # dry run (default)
     uv run python scripts/configure_b2_lifecycle.py --apply   # actually write the rules
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import b2sdk.v2 as v2

_ENV = Path(__file__).resolve().parents[1] / ".env"

# The exact b2sdk LifecycleRule shape (raw_api.LifecycleRule TypedDict): fileNamePrefix +
# daysFromUploadingToHiding + daysFromHidingToDeleting. Minimum value for each window is 1.
MANAGED_RULES: list[dict[str, object]] = [
    {"fileNamePrefix": "byo/", "daysFromUploadingToHiding": 1, "daysFromHidingToDeleting": 1},
    {"fileNamePrefix": "ingest/", "daysFromUploadingToHiding": 7, "daysFromHidingToDeleting": 1},
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


def _normalize(rule: dict[str, object]) -> dict[str, object]:
    """A comparable view of one rule: B2 echoes unset optional fields back as null; drop them so an
    echoed rule compares equal to the rule we would write."""
    return {k: v for k, v in rule.items() if v is not None}


def plan(existing: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[str]]:
    """Pure planning: (the full rule set to write, the human-readable changes). Preserves every
    existing rule whose fileNamePrefix is not managed here; adds or replaces the managed ones.
    changes is empty when the bucket already matches (nothing to write)."""
    desired = {str(r["fileNamePrefix"]): r for r in MANAGED_RULES}
    kept = [r for r in existing if str(r.get("fileNamePrefix")) not in desired]
    changes: list[str] = []
    for prefix, rule in desired.items():
        current = next((r for r in existing if str(r.get("fileNamePrefix")) == prefix), None)
        if current is None:
            changes.append(f"add rule for {prefix!r}: {json.dumps(_normalize(rule))}")
        elif _normalize(current) != _normalize(rule):
            changes.append(
                f"replace rule for {prefix!r}: "
                f"{json.dumps(_normalize(current))} -> {json.dumps(_normalize(rule))}"
            )
    return kept + list(desired.values()), changes


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

    existing: list[dict[str, object]] = [dict(r) for r in (bucket.lifecycle_rules or [])]
    print(f"bucket: {bucket_name}")
    print(f"existing lifecycle rules ({len(existing)}):")
    print(json.dumps(existing, indent=2))
    new_rules, changes = plan(existing)
    if not changes:
        print("OK: the managed lifecycle rules are already in place and identical; nothing to do")
        return
    print("changes:")
    for change in changes:
        print(f"  - {change}")
    print(
        "note: byo/ uploads are hidden after 1 day and deleted 1 day later (~2 days total); "
        "ingest/ after 7+1 (~8 days total). The registered manifest, PDQ fingerprint, and "
        "transparency-log leaf persist in the registry, so recovery outlives the deleted upload."
    )
    print("would write" if not apply else "writing", "this full lifecycle rule set:")
    print(json.dumps(new_rules, indent=2))
    if not apply:
        print("dry run (default): nothing was changed. Re-run with --apply to write it.")
        return
    bucket.update(lifecycle_rules=new_rules)
    fresh = bucket.get_fresh_state()
    print(f"OK: lifecycle rules set on {bucket_name}; bucket now reports:")
    print(json.dumps([dict(r) for r in (fresh.lifecycle_rules or [])], indent=2))


if __name__ == "__main__":
    main()
