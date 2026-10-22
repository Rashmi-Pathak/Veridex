"""Merkle transparency log: append-only proof that a manifest existed and was not altered.

Each manifest's canonical hash becomes a leaf. Periodically the signed tree head (a checkpoint) is
written to B2 under Object Lock, so the ledger is tamper-evident: no one, including the operator,
can rewrite history without contradicting a checkpoint that physically cannot be deleted.
"""

from __future__ import annotations

import base64
import binascii
import threading
from dataclasses import dataclass, field
from typing import Protocol, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pymerkle import (
    InmemoryTree,
    InvalidProof,
    MerkleProof,
    verify_consistency,
    verify_inclusion,
)

from .models import MerkleCheckpoint


def _checkpoint_head(
    epoch: int, tree_size: int, root_hex: str, signed_at: str | None = None
) -> bytes:
    """The exact bytes a checkpoint signs over. signed_at is bound into the signature so a
    checkpoint's timestamp is authenticated (mutating it breaks verification). signed_at defaults
    to None only to reconstruct the LEGACY head for verifying checkpoints sealed before signed_at
    was bound (they are immutable in B2 Object Lock and must still verify)."""
    base = f"rooted-checkpoint:{epoch}:{tree_size}:{root_hex}"
    return (f"{base}:{signed_at}" if signed_at is not None else base).encode()


class LeafStore(Protocol):
    """Durable, ordered record of the leaves so the in-memory tree can be rebuilt after a restart.

    Implemented in-memory here and by PostgresTransparencyStore for the deployed path.
    """

    def append(self, manifest_id: str, leaf_hash: str) -> None: ...
    def all(self) -> list[tuple[str, str]]: ...  # (manifest_id, leaf_hash) in append order


@dataclass
class InMemoryLeafStore:
    """Non-durable leaf store for the credential-free demo and tests."""

    leaves: list[tuple[str, str]] = field(default_factory=list)

    def append(self, manifest_id: str, leaf_hash: str) -> None:
        self.leaves.append((manifest_id, leaf_hash))

    def all(self) -> list[tuple[str, str]]:
        return list(self.leaves)


class TransparencyLog:
    """An in-memory Merkle tree plus a manifest-id -> leaf-index map, both rebuilt on construction
    from a durable LeafStore. Persisting the ordered leaves (and replaying them) means inclusion
    proofs survive a restart or a second instance, instead of resetting to an empty tree."""

    def __init__(self, leaf_store: LeafStore | None = None) -> None:
        # One reentrant lock guards every mutation and every multi-read snapshot of the shared tree,
        # so a concurrent append (the routes run in a threadpool) can never interleave with a read
        # that spans more than one access (snapshot, signed_proof). RLock so a locked method may
        # call another locked method without self-deadlock.
        self._lock = threading.RLock()
        self._tree = InmemoryTree(algorithm="sha256")
        self._index: dict[str, int] = {}
        self._store: LeafStore = leaf_store if leaf_store is not None else InMemoryLeafStore()
        for manifest_id, leaf_hash in self._store.all():
            self._index[manifest_id] = self._tree.append_entry(leaf_hash.encode())

    def append(self, manifest_id: str, leaf_hash: str) -> int:
        """Add a manifest's canonical hash as a leaf (persisting it); return its 1-based index."""
        with self._lock:
            position: int = self._tree.append_entry(leaf_hash.encode())
            self._index[manifest_id] = position
            self._store.append(manifest_id, leaf_hash)
            return position

    def index_for(self, manifest_id: str) -> int | None:
        return self._index.get(manifest_id)

    def entries(self) -> list[tuple[int, str, str]]:
        """The ordered log entries as (leaf_index, manifest_id, leaf_hash). A transparency log is
        meant to be auditable, so exposing the append-ordered leaves is by design."""
        return [(i, mid, leaf_hash) for i, (mid, leaf_hash) in enumerate(self._store.all())]

    def snapshot(self) -> tuple[list[tuple[int, str, str]], int, bytes]:
        """The entries, tree size, and root read under the lock in one pass, so the leaf list, the
        size, and the root cannot disagree even under a concurrent append from another thread."""
        with self._lock:
            entries = self.entries()
            size = self.size
            return entries, size, self.root(size)

    def close(self) -> None:
        """Release the leaf store's resources (e.g. a Postgres pool); a no-op for in-memory."""
        close = getattr(self._store, "close", None)
        if callable(close):
            close()

    @property
    def size(self) -> int:
        return cast(int, self._tree.get_size())

    def root(self, size: int | None = None) -> bytes:
        return cast(bytes, self._tree.get_state(size))

    def prove_inclusion(self, index: int, size: int | None = None) -> MerkleProof:
        return self._tree.prove_inclusion(index, size)

    def verify_inclusion(self, index: int, proof: MerkleProof, root: bytes) -> bool:
        base = self._tree.get_leaf(index)
        try:
            verify_inclusion(base, root, proof)
            return True
        except InvalidProof:
            return False

    def prove_consistency(self, prior_size: int, size: int | None = None) -> MerkleProof:
        return self._tree.prove_consistency(prior_size, size)

    def verify_consistency(
        self, prior_root: bytes, current_root: bytes, proof: MerkleProof
    ) -> bool:
        try:
            verify_consistency(prior_root, current_root, proof)
            return True
        except InvalidProof:
            return False

    def _checkpoint_for(
        self, epoch: int, tree_size: int, root_hex: str, priv: Ed25519PrivateKey, signed_at: str
    ) -> MerkleCheckpoint:
        """Sign a checkpoint over a GIVEN tree state, so callers can pin it to the exact size/root
        they already read (rather than re-reading the live tree and risking a divergent state)."""
        signature = priv.sign(_checkpoint_head(epoch, tree_size, root_hex, signed_at))
        return MerkleCheckpoint(
            epoch=epoch,
            tree_size=tree_size,
            root_hash=root_hex,
            signed_at=signed_at,
            signature_b64=base64.b64encode(signature).decode(),
        )

    def checkpoint(self, epoch: int, priv: Ed25519PrivateKey, signed_at: str) -> MerkleCheckpoint:
        with self._lock:
            return self._checkpoint_for(epoch, self.size, self.root().hex(), priv, signed_at)

    def signed_proof(
        self, index: int, priv: Ed25519PrivateKey, signed_at: str
    ) -> tuple[int, bytes, MerkleProof, MerkleCheckpoint, bool]:
        """An inclusion proof and the signed checkpoint that pins it, computed under one lock so the
        proof's root, the returned root, and the checkpoint all describe the SAME tree state.
        Returns (tree_size, root, proof, checkpoint, server_verified)."""
        with self._lock:
            size = self.size
            root = self.root(size)
            proof = self.prove_inclusion(index, size)
            verified = self.verify_inclusion(index, proof, root)
            checkpoint = self._checkpoint_for(size, size, root.hex(), priv, signed_at)
            return size, root, proof, checkpoint, verified

    def signed_consistency(
        self, prior_size: int, priv: Ed25519PrivateKey, signed_at: str
    ) -> tuple[int, bytes, int, bytes, MerkleProof, MerkleCheckpoint, bool]:
        """A Merkle consistency proof that the current log is an append-only extension of the tree
        at `prior_size` (no earlier leaf altered or removed, only appends), plus the signed
        checkpoint that pins the current head. Computed under one lock so the prior root, the
        current root, the proof, and the checkpoint all describe one consistent pair of tree states.
        Returns (prior_size, prior_root, size, current_root, proof, checkpoint, server_verified).
        Raises ValueError if prior_size is not in 1..current_size."""
        with self._lock:
            size = self.size
            if not 1 <= prior_size <= size:
                raise ValueError(f"prior_size must be in 1..{size}, got {prior_size}")
            prior_root = self.root(prior_size)
            current_root = self.root(size)
            proof = self.prove_consistency(prior_size, size)
            verified = self.verify_consistency(prior_root, current_root, proof)
            checkpoint = self._checkpoint_for(size, size, current_root.hex(), priv, signed_at)
            return prior_size, prior_root, size, current_root, proof, checkpoint, verified


def verify_checkpoint(cp: MerkleCheckpoint, pub: Ed25519PublicKey) -> bool:
    try:
        sig = base64.b64decode(cp.signature_b64)
    except binascii.Error:
        # malformed base64; a None/non-str field is a wiring bug and should crash.
        return False
    # Current checkpoints bind signed_at; verify against that head first. Fall back to the legacy
    # head (no signed_at) so checkpoints WORM-sealed before signed_at was bound still verify. A
    # current checkpoint with a tampered signed_at fails both heads (the signature was over the
    # real signed_at), so the timestamp is authenticated going forward.
    for head in (
        _checkpoint_head(cp.epoch, cp.tree_size, cp.root_hash, cp.signed_at),
        _checkpoint_head(cp.epoch, cp.tree_size, cp.root_hash),
    ):
        try:
            pub.verify(sig, head)
            return True
        except InvalidSignature:
            continue
    return False
