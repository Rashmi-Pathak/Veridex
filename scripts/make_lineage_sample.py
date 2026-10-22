"""Build api/veridex_api/assets/lineage-sample.jpg: a real C2PA provenance lineage (an ingredient
DAG) for the lineage graph.

The root is the REAL committed demo asset (a genuine Genblaze/GMI seedream generation), so the
lineage starts from a real AI generation, not a fabricated label. Three real edits derive from it,
each a genuine signed C2PA manifest whose ingredient links are cryptographically verifiable:

  AI generation (seedream)
     |-> Cropped            (parentOf the generation)
     |-> Color adjusted     (parentOf the generation)
            \\-> Composited  (parentOf Cropped + componentOf Color adjusted)

The final composited asset embeds the whole chain, so reading it back yields the full DAG. Each node
validates as the green "Trusted" state against the C2PA conformance test trust list (the signing key
is the gitignored c2pa-rs ES256 test cert; FOR TESTING ONLY, production uses the C2PA production
trust list). The signed final asset is committed; the key is not. Run from the repo root:
`uv run python scripts/make_lineage_sample.py`.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import c2pa
from PIL import Image, ImageEnhance

from veridex_api.demo import demo_sample_bytes
from veridex_provenance.claim import (
    conformance_trust_anchors,
    conformance_trust_config,
    make_es256_signer,
    read_claim,
)

CERTS = Path("research/c2pa-test-certs")
OUT = Path("api/veridex_api/assets/lineage-sample.jpg")


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _sign_node(
    signer: c2pa.Signer,
    source_jpeg: bytes,
    title: str,
    edit_action: str | None,
    parents: list[tuple[bytes, str, str]],
) -> bytes:
    """Sign one lineage node. parents is a list of (signed_parent_bytes, parent_title, relationship)
    where relationship is "parentOf" (at most one per manifest, the C2PA rule) or "componentOf". A
    derived node carries a c2pa.opened action linking every ingredient by instance id (required by
    C2PA) plus the edit action; a root carries c2pa.created with the AI digital-source type."""
    iids = ["xmp:iid:" + str(uuid.uuid4()) for _ in parents]
    if parents:
        actions = [
            {"action": "c2pa.opened", "parameters": {"ingredientIds": iids}},
            {"action": edit_action},
        ]
    else:
        actions = [
            {
                "action": "c2pa.created",
                "digitalSourceType": (
                    "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
                ),
            }
        ]
    manifest_def = {
        "claim_generator_info": [{"name": "rooted", "version": "0.1.0"}],
        "format": "image/jpeg",
        "title": title,
        "assertions": [{"label": "c2pa.actions.v2", "data": {"actions": actions}}],
    }
    builder = c2pa.Builder(manifest_def)
    for (parent_bytes, parent_title, relationship), iid in zip(parents, iids, strict=True):
        builder.add_ingredient(
            json.dumps({"title": parent_title, "relationship": relationship, "instance_id": iid}),
            "image/jpeg",
            io.BytesIO(parent_bytes),
        )
    dest = io.BytesIO()
    builder.sign(signer, "image/jpeg", io.BytesIO(source_jpeg), dest)
    return dest.getvalue()


def main() -> None:
    signer = make_es256_signer(
        (CERTS / "es256_certs.pem").read_text(),
        (CERTS / "es256_private.key").read_bytes(),
    )

    # The root is the real committed Genblaze/GMI generation.
    gen_img = Image.open(io.BytesIO(demo_sample_bytes())).convert("RGB")
    gen = _sign_node(signer, _jpeg(gen_img), "AI generation (seedream-5.0-lite)", None, [])

    w, h = gen_img.size
    cropped_img = gen_img.crop((w // 6, h // 6, w * 5 // 6, h * 5 // 6)).resize((w, h))
    cropped = _sign_node(
        signer, _jpeg(cropped_img), "Cropped", "c2pa.cropped", [(gen, "AI generation", "parentOf")]
    )

    color_img = ImageEnhance.Color(gen_img).enhance(1.8)
    color = _sign_node(
        signer,
        _jpeg(color_img),
        "Color adjusted",
        "c2pa.color_adjustments",
        [(gen, "AI generation", "parentOf")],
    )

    comp_img = Image.blend(cropped_img.resize((w, h)), color_img.resize((w, h)), 0.5)
    composited = _sign_node(
        signer,
        _jpeg(comp_img),
        "Composited",
        "c2pa.composited",
        [(cropped, "Cropped", "parentOf"), (color, "Color adjusted", "componentOf")],
    )

    _store, valid = read_claim(composited)
    _store_t, trusted = read_claim(
        composited,
        trust_anchors=conformance_trust_anchors(),
        trust_config=conformance_trust_config(),
    )
    manifest_count = len(_store_t["manifests"])
    print(
        f"lineage manifests: {manifest_count}; validation_state no-trust: {valid}; "
        f"with the conformance trust list: {trusted}; signed bytes: {len(composited)}"
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(composited)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
