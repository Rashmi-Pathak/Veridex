"""Tests for the C2PA provenance lineage DAG (/demo/lineage + parse_lineage).

The integration test reads the committed lineage asset (a real C2PA derivation: a generation, two
edits, and a composite) through the endpoint and asserts the trusted diamond DAG. It runs in CI: the
asset and the conformance anchors are committed, no signing key needed. The unit test exercises the
parser on a synthetic store with no c2pa dependency, including an ingredient whose manifest is
absent (which must not produce a dangling edge).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from veridex_api import lineage as lineage_mod
from veridex_api.lineage import parse_lineage
from veridex_api.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_lineage_endpoint_returns_the_trusted_ingredient_dag(client: TestClient) -> None:
    r = client.get("/demo/lineage")
    assert r.status_code == 200, r.text
    body = cast(dict[str, Any], r.json())

    assert body["validationState"] in ("Trusted", "Invalid")

    nodes = body["nodes"]
    assert sorted(n["kind"] for n in nodes) == ["composite", "edit", "edit", "generation"]

    # Exactly one active node, the final composite.
    active = [n for n in nodes if n["isActive"]]
    assert len(active) == 1 and active[0]["kind"] == "composite"

    # The generation is the common root (two outgoing edges); the composite has two ingredients.
    gen_id = next(n["id"] for n in nodes if n["kind"] == "generation")
    comp_id = next(n["id"] for n in nodes if n["kind"] == "composite")
    assert len([e for e in body["edges"] if e["source"] == gen_id]) == 2
    assert len([e for e in body["edges"] if e["target"] == comp_id]) == 2

    # Every edge connects two real nodes.
    node_ids = {n["id"] for n in nodes}
    for e in body["edges"]:
        assert e["source"] in node_ids and e["target"] in node_ids

    # The generation carries its honest source action.
    gen = next(n for n in nodes if n["kind"] == "generation")
    assert gen["action"] == "c2pa.created"


def _actions(*labels: str) -> list[dict[str, Any]]:
    return [{"label": "c2pa.actions.v2", "data": {"actions": [{"action": a} for a in labels]}}]


def test_parse_lineage_builds_nodes_edges_and_skips_absent_ingredients() -> None:
    store = {
        "active_manifest": "m_comp",
        "validation_state": "Trusted",
        "manifests": {
            "m_gen": {"title": "gen", "assertions": _actions("c2pa.created"), "ingredients": []},
            "m_crop": {
                "title": "crop",
                "assertions": _actions("c2pa.opened", "c2pa.cropped"),
                "ingredients": [{"active_manifest": "m_gen", "relationship": "parentOf"}],
            },
            "m_comp": {
                "title": "comp",
                "assertions": _actions("c2pa.opened", "c2pa.composited"),
                "ingredients": [
                    {"active_manifest": "m_crop", "relationship": "parentOf"},
                    # An ingredient whose manifest is not in the store (e.g. redacted) -> no edge.
                    {"active_manifest": "m_missing", "relationship": "componentOf"},
                ],
            },
        },
    }
    parsed = parse_lineage(store)

    assert parsed["validationState"] == "Trusted"
    kinds = {n["id"]: n["kind"] for n in parsed["nodes"]}
    assert kinds == {"m_gen": "generation", "m_crop": "edit", "m_comp": "composite"}
    # The crop node's defining action skips c2pa.opened.
    crop = next(n for n in parsed["nodes"] if n["id"] == "m_crop")
    assert crop["action"] == "c2pa.cropped"
    # Edges: gen -> crop, crop -> comp. The m_missing ingredient produces no dangling edge.
    pairs = {(e["source"], e["target"]) for e in parsed["edges"]}
    assert pairs == {("m_gen", "m_crop"), ("m_crop", "m_comp")}


def test_lineage_degrades_to_empty_dag_when_asset_unreadable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing or unreadable bundled asset degrades to an empty DAG (200), never a 500: the demo
    panel renders empty instead of breaking."""
    monkeypatch.setattr(lineage_mod, "_ASSET", Path("/nonexistent/lineage-sample.jpg"))
    lineage_mod._compute_lineage.cache_clear()
    try:
        r = client.get("/demo/lineage")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["nodes"] == [] and body["edges"] == []
        assert body["validationState"] is None
    finally:
        # Restore the cache so the real asset is re-read for any later test.
        lineage_mod._compute_lineage.cache_clear()
