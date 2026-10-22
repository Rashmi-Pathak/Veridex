"""In-process dedup accounting for the B2 storage paths.

Rooted's object keys are content-addressed (an asset key is its SHA-256; the ingest paths derive
the manifest id from the content), so a repeated write or a repeated register of the same bytes is
answerable without touching Backblaze B2 again. This module counts those events honestly:

- an exists-skip: a store path skipped an upload because the object already exists under its
  content-addressed key (the bytes are already durable in B2);
- an idempotent register: a register call was answered from the existing record (the BYO
  register key cache hit, or the shared ingest core finding the manifest already registered AND
  already in the transparency log).

The counters are module-level and in-process: they start at zero on process start, are never
persisted, and never claim historical totals. GET /demo/storage reports them with that caveat.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from veridex_storage.storage import Storage

_lock = threading.Lock()
_exists_skips = 0
_idempotent_registers = 0
_since = datetime.now(UTC).isoformat()


def record_exists_skip() -> None:
    """Count one skipped write: the object already exists under its content-addressed key."""
    global _exists_skips
    with _lock:
        _exists_skips += 1


def record_idempotent_register() -> None:
    """Count one register call answered idempotently from the existing record."""
    global _idempotent_registers
    with _lock:
        _idempotent_registers += 1


def counters() -> tuple[int, int, str]:
    """(exists_skips, idempotent_registers, since_iso), read under the lock. since_iso is when this
    process started counting; the counts are in-process only and reset on restart."""
    with _lock:
        return _exists_skips, _idempotent_registers, _since


def reset() -> None:
    """Zero the counters (tests)."""
    global _exists_skips, _idempotent_registers
    with _lock:
        _exists_skips = 0
        _idempotent_registers = 0


def put_if_absent(storage: Storage, key: str, data: bytes) -> bool:
    """Write key only when it is absent, counting a skipped re-upload as a dedup event. Returns
    True when the bytes were written, False when the existing object made the write unnecessary.
    Only for content-addressed or otherwise byte-stable keys, where an existing object under the
    key already holds these exact bytes. exists() errors propagate, matching the storage layer's
    contract that an outage is never mistaken for a missing object."""
    if storage.exists(key):
        record_exists_skip()
        return False
    storage.put(key, data)
    return True
