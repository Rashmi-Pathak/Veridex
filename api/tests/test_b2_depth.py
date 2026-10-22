"""The B2 depth bundle: honest in-process dedup counters (exists-skips + idempotent registers),
the /demo/storage b2Depth section (live-read-or-unknown, never a claim), the pure bucket-properties
parser, and the configure/create scripts' pure plan functions (import-safe, no credentials, no
network)."""

from __future__ import annotations

import importlib.util
import io
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import httpx
import numpy as np
import pytest
from httpx import ASGITransport
from PIL import Image

from veridex_api import byo, dedup, sbr
from veridex_api.b2_events import ingest_stored_object
from veridex_api.checkpoint import seal_checkpoint
from veridex_api.demo import seed_demo
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker
from veridex_storage.storage import InMemoryStorage, _bucket_properties

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(autouse=True)
def _reset_dedup() -> Iterator[None]:
    dedup.reset()
    yield
    dedup.reset()


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    arr = (rng.random((64, 64, 3)) * 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryStorage]:
    """In-memory resolver/log/storage at the same seams the webhook and BYO tests use."""
    monkeypatch.setenv("B2_BUCKET_DEV", "rooted-dev")
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(TransparencyLog())
    st = InMemoryStorage()
    sbr.set_storage(st)
    byo._REGISTERED_KEYS.clear()
    yield st
    byo._REGISTERED_KEYS.clear()
    sbr.set_resolver(None)
    sbr.set_log(None)
    sbr.set_storage(None)


# --- the dedup counters --------------------------------------------------------------------------


def test_put_if_absent_writes_once_and_counts_the_skip() -> None:
    storage = InMemoryStorage()
    assert dedup.put_if_absent(storage, "assets/aa/bb/aabb", b"bytes") is True
    assert dedup.put_if_absent(storage, "assets/aa/bb/aabb", b"bytes") is False
    exists_skips, idempotent_registers, since = dedup.counters()
    assert exists_skips == 1
    assert idempotent_registers == 0
    assert since  # the process-start timestamp travels with the counts


def test_seed_rerun_skips_objects_already_in_storage() -> None:
    # A restart re-seeds the same bytes under the same content-addressed keys: the second pass
    # (fresh resolver + log, SAME storage) must skip the re-uploads and count them.
    storage = InMemoryStorage()
    seed_demo(Resolver(InMemoryIndex(), FakeWatermarker()), TransparencyLog(), storage)
    dedup.reset()
    seed_demo(Resolver(InMemoryIndex(), FakeWatermarker()), TransparencyLog(), storage)
    exists_skips, _, _ = dedup.counters()
    assert exists_skips > 0


def test_seal_checkpoint_counts_the_existing_epoch_skip() -> None:
    log = TransparencyLog()
    log.append("urn:c2pa:test-seal", "ab" * 32)
    checkpoint = log.checkpoint(log.size, sbr._signing_key, "2026-07-01T00:00:00Z")
    storage = InMemoryStorage()
    key = seal_checkpoint(storage, checkpoint, retain_days=1)
    assert seal_checkpoint(storage, checkpoint, retain_days=1) == key  # skip, not a re-write
    exists_skips, _, _ = dedup.counters()
    assert exists_skips == 1


async def test_ingest_stored_object_counts_the_idempotent_redelivery(
    wired: InMemoryStorage,
) -> None:
    data = _png(1)
    image = Image.open(io.BytesIO(data)).convert("RGB")
    _, first_already = await ingest_stored_object(
        "ingest/a.png", "rooted-dev", data, image, source="test"
    )
    _, second_already = await ingest_stored_object(
        "ingest/a.png", "rooted-dev", data, image, source="test"
    )
    assert first_already is False
    assert second_already is True
    _, idempotent_registers, _ = dedup.counters()
    assert idempotent_registers == 1


async def test_byo_register_cache_hit_counts_idempotent(wired: InMemoryStorage) -> None:
    key = "byo/" + "ab12" * 8 + ".png"
    wired.put(key, _png(2))
    async with _client() as c:
        first = await c.post("/demo/byo/register", json={"objectKey": key})
        second = await c.post("/demo/byo/register", json={"objectKey": key})
    assert first.status_code == 200 and first.json()["alreadyRegistered"] is False
    assert second.status_code == 200 and second.json()["alreadyRegistered"] is True
    _, idempotent_registers, _ = dedup.counters()
    assert idempotent_registers == 1


# --- the /demo/storage b2Depth section ------------------------------------------------------------


def _assert_unread_depth(depth: dict[str, object]) -> None:
    enc = depth["defaultEncryption"]
    assert enc == {"read": False, "mode": None, "algorithm": None}
    lc = depth["lifecycle"]
    assert lc == {"read": False, "rules": None, "byoRuleActive": None, "ingestRuleActive": None}
    dd = depth["dedup"]
    assert isinstance(dd, dict)
    assert isinstance(dd["existsSkips"], int)
    assert isinstance(dd["idempotentRegisters"], int)
    assert "since process start" in str(dd["note"])


async def test_demo_storage_b2_depth_is_honestly_unknown_in_memory(
    wired: InMemoryStorage,
) -> None:
    # In-memory storage is not B2: the panel must report backend "in-memory" and every live-read
    # field as unread/unknown, while the dedup counters stay real.
    async with _client() as c:
        r = await c.get("/demo/storage")
    assert r.status_code == 200
    depth = r.json()["b2Depth"]
    assert depth["backend"] == "in-memory"
    assert depth["bucket"] is None
    _assert_unread_depth(depth)


async def test_demo_storage_b2_depth_with_no_storage_configured() -> None:
    sbr.set_storage(None)
    try:
        async with _client() as c:
            r = await c.get("/demo/storage")
        assert r.status_code == 200
        body = r.json()
        assert body["backend"] == "none"
        depth = body["b2Depth"]
        assert depth["backend"] == "none"
        _assert_unread_depth(depth)
    finally:
        sbr.set_storage(None)


async def test_demo_storage_b2_depth_carries_live_counter_values(wired: InMemoryStorage) -> None:
    dedup.record_exists_skip()
    dedup.record_idempotent_register()
    dedup.record_idempotent_register()
    async with _client() as c:
        r = await c.get("/demo/storage")
    dd = r.json()["b2Depth"]["dedup"]
    assert dd["existsSkips"] == 1
    assert dd["idempotentRegisters"] == 2


# --- the pure bucket-properties parser ------------------------------------------------------------


class _Enum:
    def __init__(self, value: object) -> None:
        self.value = value


class _Setting:
    def __init__(self, mode: object, algorithm: object) -> None:
        self.mode = _Enum(mode)
        self.algorithm = _Enum(algorithm) if algorithm is not None else None


class _FreshBucket:
    def __init__(self, mode: object, algorithm: object, rules: list[dict[str, object]]) -> None:
        self.default_server_side_encryption = _Setting(mode, algorithm)
        self.lifecycle_rules = rules


def test_bucket_properties_parses_the_b2sdk_shape() -> None:
    rules = [{"fileNamePrefix": "byo/", "daysFromUploadingToHiding": 1}]
    props = _bucket_properties(_FreshBucket("SSE-B2", "AES256", rules))
    assert props.default_encryption_mode == "SSE-B2"
    assert props.default_encryption_algorithm == "AES256"
    assert props.lifecycle_rules == rules


def test_bucket_properties_reports_unknown_encryption_as_none() -> None:
    # b2sdk's EncryptionMode.UNKNOWN carries value None (a key without readBucketEncryption).
    props = _bucket_properties(_FreshBucket(None, None, []))
    assert props.default_encryption_mode is None
    assert props.default_encryption_algorithm is None
    assert props.lifecycle_rules == []


# --- the scripts: import-safe, pure plan functions ------------------------------------------------


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # import-safe: main() only runs under __main__
    return module


def test_lifecycle_plan_adds_rules_and_preserves_foreign_ones() -> None:
    lifecycle = _load_script("configure_b2_lifecycle")
    foreign = {"fileNamePrefix": "logs/", "daysFromHidingToDeleting": 30}
    new_rules, changes = lifecycle.plan([foreign])
    assert len(changes) == 2  # byo/ and ingest/ both added
    assert foreign in new_rules
    prefixes = {r["fileNamePrefix"] for r in new_rules}
    assert prefixes == {"logs/", "byo/", "ingest/"}


def test_lifecycle_plan_is_idempotent_against_the_b2_echo() -> None:
    lifecycle = _load_script("configure_b2_lifecycle")
    # B2 echoes unset optional fields back as null; an echoed managed rule must compare equal.
    echoed = [
        {
            "fileNamePrefix": "byo/",
            "daysFromUploadingToHiding": 1,
            "daysFromHidingToDeleting": 1,
            "daysFromStartingToCancelingUnfinishedLargeFiles": None,
        },
        {
            "fileNamePrefix": "ingest/",
            "daysFromUploadingToHiding": 7,
            "daysFromHidingToDeleting": 1,
        },
    ]
    _, changes = lifecycle.plan(echoed)
    assert changes == []


def test_lifecycle_plan_replaces_a_stale_managed_rule() -> None:
    lifecycle = _load_script("configure_b2_lifecycle")
    stale = [{"fileNamePrefix": "byo/", "daysFromUploadingToHiding": 30}]
    new_rules, changes = lifecycle.plan(stale)
    assert len(changes) == 2  # byo/ replaced, ingest/ added
    byo_rules = [r for r in new_rules if r["fileNamePrefix"] == "byo/"]
    assert byo_rules == [
        {"fileNamePrefix": "byo/", "daysFromUploadingToHiding": 1, "daysFromHidingToDeleting": 1}
    ]


def test_sse_plan_covers_already_set_unset_and_unknown() -> None:
    sse = _load_script("configure_b2_sse")
    assert sse.plan("SSE-B2", "AES256")[0] is False
    needed, description = sse.plan("none", None)
    assert needed is True and "SSE-B2" in description
    needed, description = sse.plan(None, None)
    assert needed is True and "UNKNOWN" in description


def test_scoped_key_plan_is_the_exact_least_privilege_request() -> None:
    scoped = _load_script("create_b2_scoped_key")
    request = scoped.plan("rooted-dev")
    assert request["keyName"] == "veridex-api-scoped"
    assert request["capabilities"] == [
        "listBuckets",
        "readFiles",
        "writeFiles",
        "listFiles",
        "readBucketEncryption",
        "readBucketLifecycleRules",
    ]
    assert request["bucketName"] == "rooted-dev"
    assert request["bucketNames"] == ["rooted-dev"]
    assert request["namePrefix"] is None  # bucket-only restriction; byo/ shape enforced in byo.py

    # --include-locked: both buckets, plus exactly the two retention capabilities the
    # Object-Lock checkpoint paths need (write with compliance retention, read it back).
    both = scoped.plan("rooted-dev", "rooted-locked")
    assert both["bucketNames"] == ["rooted-dev", "rooted-locked"]
    assert both["capabilities"] == request["capabilities"] + [
        "writeFileRetentions",
        "readFileRetentions",
    ]
