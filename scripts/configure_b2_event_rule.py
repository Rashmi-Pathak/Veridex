"""One-shot: configure the Backblaze B2 Event Notification rule that drives Rooted's event-ingest
webhook. Reads B2 credentials + the signing secret from .env (no secret literal in this file).

The rule POSTs a signed webhook to Rooted whenever an object is created under the watched prefix;
the webhook verifies the HMAC, fetches the object from B2, and registers it for recovery. The same
signing secret must also be set as B2_EVENT_SIGNING_SECRET on the API service so the webhook can
verify the signature.

Run: uv run python scripts/configure_b2_event_rule.py
"""

from __future__ import annotations

from pathlib import Path

import b2sdk.v2 as v2

_ENV = Path(__file__).resolve().parents[1] / ".env"
_DEFAULT_WEBHOOK = "https://veridex-api-ubvc.onrender.com/webhooks/b2-event"


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.split(" #", 1)[0].strip().strip('"').strip("'")
    return out


def main() -> None:
    env = _env()
    secret = env["B2_EVENT_SIGNING_SECRET"]
    if not (len(secret) == 32 and secret.isalnum()):
        raise SystemExit("B2_EVENT_SIGNING_SECRET must be 32 alphanumeric characters")
    prefix = env.get("B2_EVENT_PREFIX", "ingest/")
    webhook = env.get("B2_EVENT_WEBHOOK_URL", _DEFAULT_WEBHOOK)

    api = v2.B2Api(v2.InMemoryAccountInfo())
    api.authorize_account("production", env["B2_KEY_ID"], env["B2_APP_KEY"])
    bucket = api.get_bucket_by_name(env["B2_BUCKET_DEV"])

    rule: v2.NotificationRule = {
        "name": "rooted-ingest",
        "eventTypes": ["b2:ObjectCreated:*"],
        "isEnabled": True,
        "objectNamePrefix": prefix,
        "targetConfiguration": {
            "targetType": "webhook",
            "url": webhook,
            "hmacSha256SigningSecret": secret,
        },
    }
    bucket.set_notification_rules([rule])

    print("OK: B2 event notification rule set on", env["B2_BUCKET_DEV"])
    for r in bucket.get_notification_rules():
        tc = r.get("targetConfiguration", {})
        print(
            f"  rule={r.get('name')} enabled={r.get('isEnabled')} "
            f"prefix={r.get('objectNamePrefix')!r} events={r.get('eventTypes')} "
            f"url={tc.get('url')} signed={'hmacSha256SigningSecret' in tc}"
        )


if __name__ == "__main__":
    main()
