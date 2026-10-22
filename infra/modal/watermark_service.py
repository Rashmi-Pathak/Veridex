"""The Rooted watermark service on Modal: real TrustMark variant P embed and decode over HTTP.

The lean Render API deliberately ships without torch, so its watermark half degrades honestly.
This service carries the model instead: a CPU container with the TrustMark P weights baked into
the image at build time (nothing downloads at request time), exposed as two small endpoints the
API calls with a shared-secret header. Rooted's remark-failover demonstration then runs BOTH
halves live in production: the real embed, the real removal attack, the real decode failure, and
the real fingerprint recovery.

Deploy:  uvx modal deploy infra/modal/watermark_service.py
Secret:  uvx modal secret create rooted-watermark-auth VERIDEX_WATERMARK_TOKEN=<random hex>
Auth:    every request must carry X-Veridex-Token matching that secret.
"""

import hmac
import io
import os

import modal

TRUSTMARK_PIN = "trustmark==0.9.1"  # match the repo's locked version

app = modal.App("veridex-watermark")


def bake_weights() -> None:
    """Instantiate TrustMark once at image-build time so the model weights are baked into the
    image layer; request-time cold starts then load from disk instead of the network."""
    from trustmark import TrustMark

    TrustMark(
        verbose=False,
        model_type="P",
        encoding_type=TrustMark.Encoding.BCH_SUPER,
        loadRemover=False,
    )


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.10.0", "torchvision==0.25.0", index_url="https://download.pytorch.org/whl/cpu"
    )
    .pip_install(TRUSTMARK_PIN, "fastapi[standard]==0.128.0", "pillow>=11", "python-multipart")
    .run_function(bake_weights)
)


@app.function(
    image=image,
    cpu=2.0,
    memory=2048,
    secrets=[modal.Secret.from_name("rooted-watermark-auth")],
    min_containers=0,
    scaledown_window=300,
)
@modal.concurrent(max_inputs=4)
@modal.asgi_app()
def web():
    from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
    from fastapi.responses import Response
    from PIL import Image
    from trustmark import TrustMark

    tm = TrustMark(
        verbose=False,
        model_type="P",
        encoding_type=TrustMark.Encoding.BCH_SUPER,
        loadRemover=False,
    )
    max_chars = tm.schemaCapacity() // 7

    api = FastAPI(title="rooted-watermark", docs_url=None, redoc_url=None, openapi_url=None)

    def check_token(x_rooted_token: str = Header(default="")) -> None:
        expected = os.environ.get("VERIDEX_WATERMARK_TOKEN", "")
        # Constant-time compare (encoded, so a non-ASCII header is a clean 401, not a 500), matching
        # the main API's ingest-key gate; a plain != leaks length/prefix via timing.
        ok = bool(expected) and hmac.compare_digest(
            x_rooted_token.encode("utf-8"), expected.encode("utf-8")
        )
        if not ok:
            raise HTTPException(status_code=401, detail="bad or missing X-Veridex-Token")

    def load_image(data: bytes) -> Image.Image:
        if len(data) > 26_214_400:
            raise HTTPException(status_code=413, detail="image too large")
        try:
            img = Image.open(io.BytesIO(data))
            # Decompression-bomb guard: the header carries the dimensions before any pixels are
            # materialized, so reject an oversized canvas here (like the main API's decode guard).
            width, height = img.size
            if width * height > 50_000_000:
                raise HTTPException(status_code=413, detail="image dimensions too large")
            return img.convert("RGB")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=415, detail="not a decodable image") from exc

    @api.get("/healthz")
    def healthz() -> dict[str, str]:
        # Unauthenticated liveness only; carries no data.
        return {"service": "rooted-watermark", "model": "trustmark-P/BCH_SUPER"}

    @api.post("/decode", dependencies=[Depends(check_token)])
    async def decode(file: UploadFile = File(...)) -> dict[str, object]:
        img = load_image(await file.read())
        # Exactly the local wrapper's semantics (veridex_provenance.watermark): text mode, and
        # confidence is the honest binary presence signal, not the schema byte.
        secret, present, _schema = tm.decode(img, MODE="text")
        return {"decodedId": secret if present else None, "confidence": 1.0 if present else 0.0}

    @api.post("/embed", dependencies=[Depends(check_token)])
    async def embed(file: UploadFile = File(...), watermark_id: str = Form(...)) -> Response:
        if not watermark_id or len(watermark_id) > max_chars:
            raise HTTPException(
                status_code=400, detail=f"watermark id must be 1..{max_chars} chars"
            )
        img = load_image(await file.read())
        marked = tm.encode(img, watermark_id, MODE="text")
        buf = io.BytesIO()
        marked.save(buf, "PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    return api
