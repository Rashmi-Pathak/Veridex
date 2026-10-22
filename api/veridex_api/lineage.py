"""C2PA provenance lineage: parse the ingredient DAG from a credentialed asset, for the graph.

GET /demo/lineage reads the bundled lineage asset (a real C2PA derivation: a generation, two edits,
and a composite, each a signed manifest with cryptographically-linked ingredients) and returns the
ingredient DAG as nodes + edges for the front-end force graph. Validation runs against the C2PA
conformance test trust list, so the lineage carries the green "Trusted" state honestly (the signing
certificate is FOR TESTING ONLY; production validates against the C2PA production trust list). The
asset is static, so the parsed DAG is computed once and cached.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from veridex_provenance.claim import (
    conformance_trust_anchors,
    conformance_trust_config,
    read_claim,
)
from veridex_provenance.models import CamelModel

logger = logging.getLogger(__name__)
router = APIRouter()

_ASSET = Path(__file__).parent / "assets" / "lineage-sample.jpg"


def _primary_action(manifest: dict[str, Any]) -> str | None:
    """The manifest's defining action: the create action for a root, or the edit action for a
    derived node. c2pa.opened is the ingredient-linking action, not the edit, so it is skipped."""
    for assertion in manifest.get("assertions", []):
        if (assertion.get("label") or "").startswith("c2pa.actions"):
            # `data` can be present-and-None on an odd store; `(... or {})` guards that, while
            # `.get("data", {})` alone would not (the default only applies when the key is absent).
            for act in (assertion.get("data") or {}).get("actions") or []:
                action = act.get("action")
                if action and action != "c2pa.opened":
                    return str(action)
    return None


def parse_lineage(store: dict[str, Any]) -> dict[str, Any]:
    """Turn a C2PA manifest store into the ingredient DAG: one node per manifest, one edge per
    ingredient (from the ingredient's referenced manifest to the manifest that consumed it)."""
    manifests: dict[str, Any] = store.get("manifests", {})
    active = store.get("active_manifest")
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for manifest_id, manifest in manifests.items():
        ingredients = manifest.get("ingredients", [])
        if not ingredients:
            kind = "generation"
        elif any(i.get("relationship") == "componentOf" for i in ingredients):
            kind = "composite"
        else:
            kind = "edit"
        nodes.append(
            {
                "id": manifest_id,
                "title": manifest.get("title"),
                "action": _primary_action(manifest),
                "kind": kind,
                "isActive": manifest_id == active,
            }
        )
        for ing in ingredients:
            parent = ing.get("active_manifest")
            if parent and parent in manifests:
                edges.append(
                    {
                        "source": parent,
                        "target": manifest_id,
                        "relationship": ing.get("relationship"),
                    }
                )
    return {"nodes": nodes, "edges": edges, "validationState": store.get("validation_state")}


@lru_cache(maxsize=1)
def _compute_lineage() -> dict[str, Any]:
    """Read the bundled lineage asset against the conformance test trust list and parse its DAG.
    Cached: the asset is static, so this runs once. On any read/parse failure (a missing or
    unreadable asset) return an empty DAG so the demo panel degrades to empty rather than 500ing;
    the asset is static, so caching the empty result avoids retrying a broken read every request."""
    try:
        store, _state = read_claim(
            _ASSET.read_bytes(),
            trust_anchors=conformance_trust_anchors(),
            trust_config=conformance_trust_config(),
        )
        return parse_lineage(store)
    except Exception as exc:  # noqa: BLE001 - the demo panel must never 500; degrade to empty
        logger.warning("lineage asset could not be read; serving an empty DAG: %s", exc)
        return {"nodes": [], "edges": [], "validationState": None}


class LineageResponse(CamelModel):
    """The C2PA ingredient DAG for the front-end force graph. nodes are manifests (a generation, the
    edits, the composite); edges point from an ingredient's manifest to the manifest that used it.
    validationState is the whole chain's state ("Trusted" against the conformance trust list)."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    validation_state: str | None


@router.get("/demo/lineage", response_model=LineageResponse, include_in_schema=False)
async def demo_lineage() -> LineageResponse:
    """Return the C2PA provenance lineage DAG parsed from the bundled credentialed asset."""
    parsed = await run_in_threadpool(_compute_lineage)
    return LineageResponse(
        nodes=parsed["nodes"], edges=parsed["edges"], validation_state=parsed["validationState"]
    )
