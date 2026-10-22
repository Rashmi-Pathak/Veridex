"""Tests for the Object-Lock checkpoint surface (/transparency/checkpoint/object).

A signed Merkle checkpoint is sealed under compliance Object Lock and read back: the modeled path
(no locked bucket) runs the same write/read/verify/lock contract against the in-memory model and
labels itself, and the real-bucket path is exercised with an in-memory store injected as the locked
backend (the same Storage protocol B2 implements). Network-free.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from veridex_api import sbr
from veridex_api.checkpoint import seal_checkpoint
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.models import MerkleCheckpoint
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker
from veridex_storage.storage import InMemoryStorage, ObjectLockedError, checkpoint_key


def _log_with_leaves(n: int) -> TransparencyLog:
    log = TransparencyLog()
    for i in range(n):
        log.append(f"urn:c2pa:demo-{i}", f"{i:064x}")
    return log


@pytest.fixture
def reset() -> Iterator[None]:
    yield
    sbr.set_resolver(None)
    sbr.set_log(None)
    sbr.set_storage(None)
    sbr.set_locked_storage(None)


def test_checkpoint_object_modeled_when_no_locked_bucket(reset: None) -> None:
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(_log_with_leaves(3))
    sbr.set_storage(None)
    sbr.set_locked_storage(None)  # no B2_BUCKET_LOCKED -> the surface models Object Lock, labeled
    with TestClient(app) as c:
        d = c.get("/transparency/checkpoint/object").json()
    assert d["backend"] == "in-memory"
    assert d["modeled"] is True
    assert d["immutable"] is True
    assert d["retentionMode"] == "compliance"
    assert d["retainUntil"] is not None
    assert d["signatureVerified"] is True
    assert d["checkpoint"]["treeSize"] == 3
    assert d["keySource"] in {"configured", "ephemeral"}


def test_checkpoint_object_real_locked_bucket(reset: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B2_BUCKET_LOCKED", "rooted-checkpoints")
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(_log_with_leaves(2))
    sbr.set_storage(None)
    # an in-memory store stands in for the fileLock-enabled B2 bucket (the same Storage protocol)
    locked = InMemoryStorage()
    sbr.set_locked_storage(locked)
    with TestClient(app) as c:
        d = c.get("/transparency/checkpoint/object").json()
        # idempotent: a second read does not re-write the compliance-retained object
        assert c.get("/transparency/checkpoint/object").status_code == 200
    assert d["backend"] == "backblaze-b2"
    assert d["modeled"] is False
    assert d["bucket"] == "rooted-checkpoints"
    assert d["immutable"] is True
    assert d["signatureVerified"] is True
    # the checkpoint was actually sealed under Object Lock and cannot be deleted or overwritten
    key = checkpoint_key(d["checkpoint"]["epoch"])
    assert locked.exists(key)
    with pytest.raises(ObjectLockedError):
        locked.delete(key)
    with pytest.raises(ObjectLockedError):
        locked.put(key, b"tampered", object_lock=True, retain_days=1)


def test_seal_checkpoint_is_idempotent_and_immutable() -> None:
    cp = MerkleCheckpoint(
        epoch=5, tree_size=5, root_hash="ab" * 32, signed_at="t", signature_b64="x"
    )
    s = InMemoryStorage()
    k1 = seal_checkpoint(s, cp, 30)
    # already exists, so it is left as-is (no overwrite, hence no ObjectLockedError)
    k2 = seal_checkpoint(s, cp, 30)
    assert k1 == k2 == checkpoint_key(5)
    with pytest.raises(ObjectLockedError):
        s.delete(k1)


def test_checkpoint_history_modeled_when_no_locked_bucket(reset: None) -> None:
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(_log_with_leaves(4))
    sbr.set_storage(None)
    sbr.set_locked_storage(None)  # no locked bucket -> the chain is modeled, labeled
    with TestClient(app) as c:
        d = c.get("/demo/checkpoint-history").json()
    assert d["backend"] == "in-memory"
    assert d["modeled"] is True
    assert d["count"] == 1
    assert d["entries"][0]["treeSize"] == 4
    assert d["entries"][0]["signatureVerified"] is True
    assert d["entries"][0]["immutable"] is True


def test_checkpoint_history_real_locked_bucket_lists_the_chain(
    reset: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("B2_BUCKET_LOCKED", "rooted-locked")
    log = _log_with_leaves(2)
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(log)
    locked = InMemoryStorage()
    sbr.set_locked_storage(locked)
    # seal a chain of two epochs: at size 2, then append a leaf and seal at size 3
    seal_checkpoint(locked, sbr.current_checkpoint(), 30)
    log.append("urn:c2pa:demo-extra", "ab" * 32)
    seal_checkpoint(locked, sbr.current_checkpoint(), 30)
    with TestClient(app) as c:
        d = c.get("/demo/checkpoint-history").json()
    assert d["backend"] == "backblaze-b2"
    assert d["modeled"] is False
    assert d["bucket"] == "rooted-locked"
    assert d["count"] == 2
    assert [e["epoch"] for e in d["entries"]] == [2, 3]  # sorted by epoch
    assert all(e["signatureVerified"] for e in d["entries"])
    assert all(e["immutable"] for e in d["entries"])


class _NoListStorage(InMemoryStorage):
    """A locked store that can read but cannot LIST (mirrors a least-privilege production B2 key
    without listFiles): list_keys raises, exists/get/retention still work."""

    def list_keys(self, prefix: str) -> list[str]:
        raise PermissionError("listFiles capability not granted")


def test_checkpoint_history_reads_real_chain_by_existence_when_list_denied(
    reset: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("B2_BUCKET_LOCKED", "rooted-locked")
    log = _log_with_leaves(2)
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(log)
    locked = _NoListStorage()
    sbr.set_locked_storage(locked)
    seal_checkpoint(locked, sbr.current_checkpoint(), 30)  # epoch 2
    log.append("urn:c2pa:demo-extra", "ab" * 32)
    seal_checkpoint(locked, sbr.current_checkpoint(), 30)  # epoch 3
    with TestClient(app) as c:
        d = c.get("/demo/checkpoint-history").json()
    # list is denied, but it reads the REAL WORM chain by per-epoch existence, NOT the model
    assert d["backend"] == "backblaze-b2"
    assert d["modeled"] is False
    assert [e["epoch"] for e in d["entries"]] == [2, 3]
    assert all(e["signatureVerified"] for e in d["entries"])
    assert all(e["immutable"] for e in d["entries"])
