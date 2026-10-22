"""Storage for Rooted: a Protocol, an in-memory fake, and the Backblaze B2 backend.

Keys are content-addressable, so an asset's SHA-256 (and the manifest id) is the natural address.
Object Lock (compliance retention) makes the Merkle checkpoints tamper-evident: once written they
cannot be deleted until retention expires, which is exactly what an audit trail needs.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

ASSET_PREFIX = "assets"
MANIFEST_PREFIX = "manifests"
SIGNATURE_PREFIX = "signatures"
CHECKPOINT_PREFIX = "merkle/checkpoints"


def asset_key(sha256: str) -> str:
    """Content-addressable asset key, sharded by the first hash bytes to spread the keyspace."""
    return f"{ASSET_PREFIX}/{sha256[:2]}/{sha256[2:4]}/{sha256}"


def manifest_key(manifest_id: str) -> str:
    return f"{MANIFEST_PREFIX}/{manifest_id.replace(':', '_')}.json"


def signature_key(manifest_id: str) -> str:
    """B2 key for the manifest's COSE signature, so the signature is durable, not caller-held."""
    return f"{SIGNATURE_PREFIX}/{manifest_id.replace(':', '_')}.cose"


def checkpoint_key(epoch: int) -> str:
    """The checkpoint is serialized as JSON (the MerkleCheckpoint model), so the key says .json."""
    return f"{CHECKPOINT_PREFIX}/epoch_{epoch:08d}.json"


@dataclass(frozen=True)
class RetentionInfo:
    """An object's Object-Lock state, read back from the store. retain_until_ms is epoch millis."""

    mode: str  # "compliance" | "governance" | "none"
    retain_until_ms: int | None


def _parse_retention(file_retention: object) -> RetentionInfo:
    """Map a b2sdk FileRetentionSetting (or None) to RetentionInfo. b2sdk exposes the retain-until
    as `.retain_until` (epoch millis) and the mode as a RetentionMode enum whose `.value` is
    "compliance"/"governance" (and None for no retention). Kept as a pure helper so it can be unit
    tested against the real b2sdk object shape without B2 credentials."""
    mode = getattr(file_retention, "mode", None)
    mode_val = getattr(mode, "value", None)
    until = getattr(file_retention, "retain_until", None)
    return RetentionInfo(mode=mode_val if mode_val is not None else "none", retain_until_ms=until)


@dataclass(frozen=True)
class BucketProperties:
    """A bucket's live server-side configuration, read back from the store. The encryption mode and
    algorithm are None when the store reports them unknown (for example an application key without
    readBucketEncryption). lifecycle_rules are the raw B2 rule dicts (B2's own field names:
    fileNamePrefix, daysFromUploadingToHiding, daysFromHidingToDeleting)."""

    default_encryption_mode: str | None  # "SSE-B2" | "none" | None (unknown to this key)
    default_encryption_algorithm: str | None  # "AES256" | None
    lifecycle_rules: list[dict[str, object]]


def _bucket_properties(fresh_bucket: object) -> BucketProperties:
    """Map a b2sdk Bucket (a fresh state) to BucketProperties. b2sdk exposes the default encryption
    as an EncryptionSetting whose mode/algorithm enums carry `.value` ("SSE-B2"/"none"/"AES256";
    the UNKNOWN mode's value is None), and the lifecycle rules as a list of dicts. Kept as a pure
    helper so it is unit-testable against the real b2sdk shape without B2 credentials, like
    _parse_retention above."""
    enc = getattr(fresh_bucket, "default_server_side_encryption", None)
    mode = getattr(getattr(enc, "mode", None), "value", None)
    algorithm = getattr(getattr(enc, "algorithm", None), "value", None)
    rules = [dict(r) for r in (getattr(fresh_bucket, "lifecycle_rules", None) or [])]
    return BucketProperties(
        default_encryption_mode=mode,
        default_encryption_algorithm=algorithm,
        lifecycle_rules=rules,
    )


class ObjectLockedError(Exception):
    """Raised when a delete is attempted on an Object-Lock-retained object."""


@runtime_checkable
class Storage(Protocol):
    def put(
        self, key: str, data: bytes, *, object_lock: bool = False, retain_days: int | None = None
    ) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int | None: ...
    def delete(self, key: str) -> None: ...
    def retention(self, key: str) -> RetentionInfo | None: ...
    def list_keys(self, prefix: str) -> list[str]: ...


class InMemoryStorage:
    """Credential-free fake. Models Object Lock by refusing to delete or overwrite locked keys and
    by reporting the compliance retain-until it was written with, so the lock contract can be
    exercised end to end (write, read-back retention, refuse delete) without B2 credentials."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._retention: dict[str, RetentionInfo] = {}

    def put(
        self, key: str, data: bytes, *, object_lock: bool = False, retain_days: int | None = None
    ) -> str:
        if key in self._retention:
            raise ObjectLockedError(f"{key} is under Object Lock and cannot be overwritten")
        if object_lock and not retain_days:
            raise ValueError("object_lock requires retain_days")
        self._data[key] = bytes(data)
        if object_lock and retain_days:
            until_ms = int((time.time() + retain_days * 86400) * 1000)
            self._retention[key] = RetentionInfo(mode="compliance", retain_until_ms=until_ms)
        return key

    def get(self, key: str) -> bytes:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def exists(self, key: str) -> bool:
        return key in self._data

    def size(self, key: str) -> int | None:
        if key not in self._data:
            return None
        return len(self._data[key])

    def delete(self, key: str) -> None:
        if key in self._retention:
            raise ObjectLockedError(f"{key} is under Object Lock and cannot be deleted")
        self._data.pop(key, None)

    def retention(self, key: str) -> RetentionInfo | None:
        if key not in self._data:
            return None
        return self._retention.get(key, RetentionInfo(mode="none", retain_until_ms=None))

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self._data if k.startswith(prefix))


class B2Storage:
    """Real Backblaze B2 backend (b2sdk). Needs credentials, so it is verified with a live smoke
    test once keys land, not in unit tests. The InMemoryStorage fake covers the contract in CI.
    """

    def __init__(self, key_id: str, app_key: str, bucket_name: str) -> None:
        from b2sdk.v2 import B2Api, InMemoryAccountInfo

        api = B2Api(InMemoryAccountInfo())
        api.authorize_account("production", key_id, app_key)
        self._bucket = api.get_bucket_by_name(bucket_name)

    def put(
        self, key: str, data: bytes, *, object_lock: bool = False, retain_days: int | None = None
    ) -> str:
        kwargs: dict[str, object] = {}
        if object_lock:
            if not retain_days:
                raise ValueError("object_lock requires retain_days")
            from b2sdk.v2 import FileRetentionSetting, RetentionMode

            until_ms = int((time.time() + retain_days * 86400) * 1000)
            kwargs["file_retention"] = FileRetentionSetting(RetentionMode.COMPLIANCE, until_ms)
        self._bucket.upload_bytes(bytes(data), key, **kwargs)
        return key

    def get(self, key: str) -> bytes:
        buf = io.BytesIO()
        self._bucket.download_file_by_name(key).save(buf)
        return buf.getvalue()

    def exists(self, key: str) -> bool:
        from b2sdk.v2.exception import FileNotPresent

        try:
            self._bucket.get_file_info_by_name(key)
            return True
        except FileNotPresent:
            # Only "absent" returns False. Connection/auth errors propagate so an outage is never
            # mistaken for a missing object (which would corrupt recovery and overwrite logic).
            return False

    def size(self, key: str) -> int | None:
        """The object's stored size in bytes, or None when it is absent. Reads only the file info
        (no download), so a size cap can be enforced before any bytes are fetched. Connection/auth
        errors propagate, like exists(), so an outage is never mistaken for a missing object."""
        from b2sdk.v2.exception import FileNotPresent

        try:
            info = self._bucket.get_file_info_by_name(key)
        except FileNotPresent:
            return None
        size = getattr(info, "size", None)
        return int(size) if size is not None else None

    def delete(self, key: str) -> None:
        info = self._bucket.get_file_info_by_name(key)
        self._bucket.delete_file_version(info.id_, key)

    def retention(self, key: str) -> RetentionInfo | None:
        """Read the object's Object-Lock retention back from B2, so the immutable retain-until is
        the bucket's own record, not something we assert. Returns None if the object is absent.
        (Reading file_retention needs the app key's readFileRetentions capability.)"""
        from b2sdk.v2.exception import FileNotPresent

        try:
            info = self._bucket.get_file_info_by_name(key)
        except FileNotPresent:
            return None
        return _parse_retention(getattr(info, "file_retention", None))

    def list_keys(self, prefix: str) -> list[str]:
        """List the object keys under a prefix (B2 has a flat namespace; "/" is a folder
        convention). Used to reconstruct the recovery index from B2 alone, so B2 is the source of
        truth, not the database. Recursive, so a sharded prefix (assets/..) is fully walked."""
        return [
            fv.file_name
            for fv, _ in self._bucket.ls(
                folder_to_list=prefix.rstrip("/"), recursive=True, latest_only=True
            )
            if fv.file_name.startswith(prefix)
        ]

    def properties(self) -> BucketProperties:
        """The bucket's live configuration (default server-side encryption + lifecycle rules), read
        fresh from B2 (one b2_list_buckets round trip, so the authorized key needs listBuckets).
        The encryption comes back as None when the key lacks readBucketEncryption; callers report
        that honestly as unknown rather than failing. Errors propagate so an outage is visible."""
        return _bucket_properties(self._bucket.get_fresh_state())
