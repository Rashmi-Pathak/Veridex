"""Object-Lock checkpoint: write the signed Merkle tree head to B2 under compliance retention.

A checkpoint is a signed (Ed25519) statement of the transparency tree's size and root at an epoch.
Writing it to a fileLock-enabled B2 bucket with COMPLIANCE retention makes the ledger tamper-evident
at the storage layer: no one, including the operator, can rewrite history without contradicting an
object that physically cannot be deleted until retention expires. The write is best-effort
idempotent per epoch: an existing-object check skips a re-write, the startup seal runs before any
traffic so the concurrent first-write race is tiny, and a retained object can never be replaced.

When B2_BUCKET_LOCKED is not configured the same contract is exercised against the in-memory model
and the surface is labeled `modeled`, so CI and the credential-free demo still prove the behavior.
The endpoint is read-back-and-verify: it re-parses the stored checkpoint, re-verifies its signature
against the published key, and reports the object's own compliance retain-until.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from veridex_api.dedup import record_exists_skip
from veridex_provenance.merkle import verify_checkpoint
from veridex_provenance.models import CamelModel, MerkleCheckpoint
from veridex_storage.storage import (
    CHECKPOINT_PREFIX,
    InMemoryStorage,
    Storage,
    checkpoint_key,
)

from . import sbr

logger = logging.getLogger(__name__)
router = APIRouter()


def _retain_days() -> int:
    """Compliance retention window for a sealed checkpoint. Long enough to cover the audit/judging
    window; configurable so the operator picks their own retention. Floored at 1 (B2 rejects 0)."""
    raw = os.environ.get("VERIDEX_CHECKPOINT_RETAIN_DAYS", "90")
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("VERIDEX_CHECKPOINT_RETAIN_DAYS=%r is not an int; defaulting to 90", raw)
        return 90


def seal_checkpoint(locked: Storage, checkpoint: MerkleCheckpoint, retain_days: int) -> str:
    """Write the signed checkpoint to the locked store under Object Lock, idempotently. A
    compliance-retained object cannot be overwritten, so if this epoch's checkpoint already exists
    we leave the existing immutable record authoritative, no re-write. Returns the object key."""
    key = checkpoint_key(checkpoint.epoch)
    if locked.exists(key):
        record_exists_skip()  # dedup evidence: this epoch's immutable object is already sealed
        return key
    body = checkpoint.model_dump_json().encode()
    locked.put(key, body, object_lock=True, retain_days=retain_days)
    return key


def seal_startup_checkpoint() -> None:
    """Best-effort: seal the current checkpoint to the locked bucket at startup, so the immutable
    object exists before any reader asks. Never raises: a missing capability or a non-locked bucket
    must not fail the deploy (the endpoint then degrades to the in-memory model, labeled)."""
    locked = sbr.get_locked_storage()
    if locked is None:
        return
    try:
        key = seal_checkpoint(locked, sbr.current_checkpoint(), _retain_days())
        logger.info("sealed startup checkpoint to the locked bucket: %s", key)
    except Exception as exc:  # noqa: BLE001 - sealing must never crash the deploy
        # The bucket was explicitly configured, so a failure here is a real misconfiguration the
        # operator needs to see (not fileLock-enabled, missing writeFileRetentions, wrong name): log
        # at ERROR, not WARNING, so it is not mistaken for the benign no-locked-bucket case.
        logger.error(
            "B2_BUCKET_LOCKED is set but the startup checkpoint could not be sealed "
            "(check the bucket is fileLock-enabled and the key has writeFileRetentions): %s",
            exc,
        )


class CheckpointObjectResponse(CamelModel):
    """The sealed checkpoint object's observable facts, read back from the store. `immutable` is
    true when the object carries an active compliance retention (the WORM proof). `modeled` is true
    when the in-memory model stands in for B2 (no locked bucket configured), and is labeled so."""

    backend: str  # "backblaze-b2" | "in-memory"
    bucket: str | None
    key: str
    retention_mode: str  # "compliance" when locked
    retain_until: str | None  # ISO 8601, the store's own record
    checkpoint: MerkleCheckpoint
    signature_verified: bool
    immutable: bool
    modeled: bool
    public_key_hex: str
    key_source: str


def _describe(
    storage: Storage, backend: str, bucket: str | None, checkpoint: MerkleCheckpoint, modeled: bool
) -> CheckpointObjectResponse:
    """Read the sealed checkpoint back, re-verify its signature, and report its retention."""
    key = checkpoint_key(checkpoint.epoch)
    stored = MerkleCheckpoint.model_validate_json(storage.get(key))
    signature_verified = verify_checkpoint(stored, sbr.signing_public_key())
    ret = storage.retention(key)
    retain_until = None
    immutable = False
    if ret is not None and ret.retain_until_ms is not None:
        retain_until = datetime.fromtimestamp(ret.retain_until_ms / 1000, UTC).isoformat()
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        immutable = ret.mode == "compliance" and ret.retain_until_ms > now_ms
    return CheckpointObjectResponse(
        backend=backend,
        bucket=bucket,
        key=key,
        retention_mode=(ret.mode if ret else "none"),
        retain_until=retain_until,
        checkpoint=stored,
        signature_verified=signature_verified,
        immutable=immutable,
        modeled=modeled,
        public_key_hex=sbr._public_key_hex(),
        key_source=sbr.key_source(),
    )


@router.get(
    "/transparency/checkpoint/object",
    response_model=CheckpointObjectResponse,
    include_in_schema=False,
)
async def checkpoint_object() -> CheckpointObjectResponse:
    """Read back the signed checkpoint sealed under B2 Object Lock and verify it. With a locked
    bucket configured it reports the real compliance retain-until from B2; otherwise it runs the
    same write/read/verify contract against the in-memory model and labels the result `modeled`."""
    checkpoint = sbr.current_checkpoint()
    locked = sbr.get_locked_storage()
    bucket = os.environ.get("B2_BUCKET_LOCKED")
    if locked is not None:
        try:
            key = checkpoint_key(checkpoint.epoch)
            if not locked.exists(key):
                seal_checkpoint(locked, checkpoint, _retain_days())
            return _describe(locked, "backblaze-b2", bucket, checkpoint, modeled=False)
        except Exception as exc:  # noqa: BLE001 - degrade to the model, never 500
            # A locked bucket was configured, so this is a real failure (B2 outage / misconfig), not
            # the benign no-bucket case: log at ERROR. The response still degrades to the labeled
            # model rather than 500ing, but the operator gets a loud signal in the logs.
            logger.error(
                "B2_BUCKET_LOCKED is set but the locked checkpoint read-back failed; "
                "serving the in-memory model: %s",
                exc,
            )
    model = InMemoryStorage()
    seal_checkpoint(model, checkpoint, _retain_days())
    return _describe(model, "in-memory", None, checkpoint, modeled=True)


class DemoConsistencyResponse(CamelModel):
    """The append-only proof, demo-framed and tied to B2 Object Lock. The current log (tree_size)
    is provably an extension of the tree at prior_size: no earlier leaf was altered or removed.
    sealed_in_object_lock is true when the prior tree state is itself WORM-sealed in B2 under active
    compliance retention and its sealed root matches the proof's prior root, so the consistency
    proof is anchored to an object that physically cannot be rewritten. available is false only when
    the log has a single leaf (nothing has been appended on top of an earlier state yet)."""

    available: bool
    prior_size: int
    prior_root_hash: str
    tree_size: int
    root_hash: str
    server_verified: bool
    sealed_in_object_lock: bool
    sealed_root_matches: bool
    backend: str
    bucket: str | None
    retain_until: str | None
    checkpoint: MerkleCheckpoint
    public_key_hex: str
    key_source: str


@router.get("/demo/consistency", response_model=DemoConsistencyResponse, include_in_schema=False)
async def demo_consistency() -> DemoConsistencyResponse:
    """Prove the live transparency log only ever appended: a Merkle consistency proof from the
    immediately-prior tree size to the current head, then a read-only check of whether that prior
    state is WORM-sealed in B2 Object Lock (binding the proof to an immutable object). Read-only:
    it never writes a checkpoint."""
    log = sbr.get_log()
    size = await run_in_threadpool(lambda: log.size)
    current = sbr.current_checkpoint()
    if size < 2:
        # A single leaf: there is no earlier state to extend yet. Honest, not an error.
        return DemoConsistencyResponse(
            available=False,
            prior_size=size,
            prior_root_hash=current.root_hash,
            tree_size=size,
            root_hash=current.root_hash,
            server_verified=False,
            sealed_in_object_lock=False,
            sealed_root_matches=False,
            backend="in-memory",
            bucket=None,
            retain_until=None,
            checkpoint=current,
            public_key_hex=sbr._public_key_hex(),
            key_source=sbr.key_source(),
        )
    prior_size = size - 1
    psize, proot, tsize, root, _proof, checkpoint, verified = await run_in_threadpool(
        log.signed_consistency, prior_size, sbr._signing_key, datetime.now(UTC).isoformat()
    )
    prior_root_hex = proot.hex()

    sealed = False
    sealed_root_matches = False
    retain_until: str | None = None
    backend = "in-memory"
    bucket = os.environ.get("B2_BUCKET_LOCKED")
    locked = sbr.get_locked_storage()
    if locked is not None:
        backend = "backblaze-b2"
        try:
            key = checkpoint_key(prior_size)
            if await run_in_threadpool(locked.exists, key):
                stored = MerkleCheckpoint.model_validate_json(
                    await run_in_threadpool(locked.get, key)
                )
                sealed_root_matches = stored.root_hash == prior_root_hex
                ret = await run_in_threadpool(locked.retention, key)
                if ret is not None and ret.retain_until_ms is not None:
                    now_ms = int(datetime.now(UTC).timestamp() * 1000)
                    sealed = ret.mode == "compliance" and ret.retain_until_ms > now_ms
                    retain_until = datetime.fromtimestamp(
                        ret.retain_until_ms / 1000, UTC
                    ).isoformat()
        except Exception as exc:  # noqa: BLE001 - the proof stands even if the B2 lookup fails
            logger.error("demo-consistency: locked-seal binding lookup failed: %s", exc)

    return DemoConsistencyResponse(
        available=True,
        prior_size=psize,
        prior_root_hash=prior_root_hex,
        tree_size=tsize,
        root_hash=root.hex(),
        server_verified=verified,
        sealed_in_object_lock=sealed and sealed_root_matches,
        sealed_root_matches=sealed_root_matches,
        backend=backend,
        bucket=bucket if locked is not None else None,
        retain_until=retain_until,
        checkpoint=checkpoint,
        public_key_hex=sbr._public_key_hex(),
        key_source=sbr.key_source(),
    )


class CheckpointHistoryEntry(CamelModel):
    """One sealed checkpoint in the epoch chain, read back from the store and re-verified. immutable
    is true when the object still carries active compliance retention (the WORM proof)."""

    epoch: int
    tree_size: int
    root_hash: str
    signed_at: str
    signature_verified: bool
    retain_until: str | None
    immutable: bool


class CheckpointHistory(CamelModel):
    """The chain of signed Merkle checkpoints sealed to B2 over time. Each is an immutable WORM
    object, so the chain is an append-only audit trail of the tree head at successive epochs;
    combined with the consistency proof, it shows the live log extends every sealed checkpoint.
    modeled is true when no locked bucket is configured and the in-memory model stands in."""

    backend: str
    bucket: str | None
    count: int
    modeled: bool
    entries: list[CheckpointHistoryEntry]


_HISTORY_CAP = 200


def _history_entry(storage: Storage, key: str) -> CheckpointHistoryEntry:
    """Read one sealed checkpoint back, re-verify its signature against the published key, and
    report its B2 Object-Lock retention (the store's own record)."""
    cp = MerkleCheckpoint.model_validate_json(storage.get(key))
    verified = verify_checkpoint(cp, sbr.signing_public_key())
    ret = storage.retention(key)
    retain_until = None
    immutable = False
    if ret is not None and ret.retain_until_ms is not None:
        retain_until = datetime.fromtimestamp(ret.retain_until_ms / 1000, UTC).isoformat()
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        immutable = ret.mode == "compliance" and ret.retain_until_ms > now_ms
    return CheckpointHistoryEntry(
        epoch=cp.epoch,
        tree_size=cp.tree_size,
        root_hash=cp.root_hash,
        signed_at=cp.signed_at,
        signature_verified=verified,
        retain_until=retain_until,
        immutable=immutable,
    )


def _history_by_exists(locked: Storage, current_size: int) -> list[CheckpointHistoryEntry]:
    """Enumerate the sealed checkpoints by checking each epoch's object existence, so a key that can
    READ but not LIST the locked bucket (a least-privilege production key) still reads the REAL WORM
    chain from B2 rather than falling back to the in-memory model. Bounded to the most recent
    _HISTORY_CAP epochs. exists() uses get_file_info (readFiles), not ls (listFiles)."""
    lo = max(1, current_size - _HISTORY_CAP + 1)
    entries: list[CheckpointHistoryEntry] = []
    for epoch in range(lo, current_size + 1):
        key = checkpoint_key(epoch)
        if locked.exists(key):
            entries.append(_history_entry(locked, key))
    return entries


@router.get("/demo/checkpoint-history", response_model=CheckpointHistory, include_in_schema=False)
async def checkpoint_history() -> CheckpointHistory:
    """The chain of signed Merkle checkpoints sealed to B2 Object Lock over time, each re-verified
    and reporting its own immutable retain-until. Reads the REAL objects from B2: a single ls when
    the key can list, else per-epoch existence checks (so a least-privilege key still reads the real
    chain). Only with no locked bucket does it seal the current checkpoint into the in-memory model
    and label it."""
    locked = sbr.get_locked_storage()
    if locked is not None:
        bucket = os.environ.get("B2_BUCKET_LOCKED")
        current_size = await run_in_threadpool(lambda: sbr.get_log().size)
        entries: list[CheckpointHistoryEntry] | None = None
        try:
            keys = await run_in_threadpool(locked.list_keys, f"{CHECKPOINT_PREFIX}/")
            entries = [
                await run_in_threadpool(_history_entry, locked, k) for k in keys[:_HISTORY_CAP]
            ]
        except Exception as exc:  # noqa: BLE001 - the key may lack listFiles; fall back to exists
            logger.warning(
                "checkpoint-history: list failed (%s); enumerating the chain by existence", exc
            )
            try:
                entries = await run_in_threadpool(_history_by_exists, locked, current_size)
            except Exception as exc2:  # noqa: BLE001 - a real B2 outage; degrade to the model
                logger.error(
                    "B2_BUCKET_LOCKED is set but both list and existence reads failed; "
                    "serving the in-memory model: %s",
                    exc2,
                )
        if entries is not None:
            entries.sort(key=lambda e: e.epoch)
            return CheckpointHistory(
                backend="backblaze-b2",
                bucket=bucket,
                count=len(entries),
                modeled=False,
                entries=entries,
            )
    model = InMemoryStorage()
    cp = sbr.current_checkpoint()
    seal_checkpoint(model, cp, _retain_days())
    entry = await run_in_threadpool(_history_entry, model, checkpoint_key(cp.epoch))
    return CheckpointHistory(
        backend="in-memory", bucket=None, count=1, modeled=True, entries=[entry]
    )
