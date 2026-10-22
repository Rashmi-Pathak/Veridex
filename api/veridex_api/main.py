"""FastAPI application entry point for the Rooted SBR API.

Exposes the C2PA v2.4 Soft Binding Resolution routes (mounted from veridex_api.sbr) plus a liveness
probe, the demo aids, the live generation and agent endpoints, and the status surface. Rooted's own
MCP server is mounted in-process at /mcp, so the curated provenance tools are reachable on the same
deploy with no separate service; its tools call this app's SBR routes through an in-process ASGI
client (no network, no credentials). The resolver (and its Postgres connection pool, when
DATABASE_URL is set) is built and validated at startup via the lifespan, so a misconfigured database
fails the deploy loudly instead of 500ing on the first user request.

The app is built by create_app(). The MCP mount is opt-out (mount_mcp=False) so the schemathesis
contract test, whose ASGI transport does not support a lifespan that sets scope "state" (which
the FastMCP streamable-HTTP session manager requires), can exercise the SBR contract on an
otherwise identical app. The MCP mount adds nothing to the OpenAPI surface, so excluding it does
not narrow the contract under test.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv

# Load .env variables (such as VERIDEX_DEMO_SEED=1, DATABASE_URL, etc.)
load_dotenv(find_dotenv(usecwd=True))

import httpx
from fastapi import FastAPI
from fastmcp.utilities.lifespan import combine_lifespans
from httpx import ASGITransport
from starlette.types import Lifespan

from veridex_api.agent import router as agent_router
from veridex_api.b2_events import router as b2_events_router
from veridex_api.byo import router as byo_router
from veridex_api.checkpoint import router as checkpoint_router
from veridex_api.checkpoint import seal_startup_checkpoint
from veridex_api.demo import router as demo_router
from veridex_api.demo import seed_audio_demo, seed_demo, seed_providers, seed_video_demo
from veridex_api.genblaze import router as genblaze_router
from veridex_api.genblaze_verify import router as genblaze_verify_router
from veridex_api.generate import router as generate_router
from veridex_api.limits import LimitRequestBodyMiddleware
from veridex_api.lineage import router as lineage_router
from veridex_api.sbr import (
    get_audio_resolver,
    get_log,
    get_resolver,
    get_storage,
    get_video_resolver,
)
from veridex_api.sbr import router as sbr_router
from veridex_api.status import router as status_router
from veridex_api.tamper import router as tamper_router
from veridex_api.transcript import router as transcript_router
from veridex_mcp import server as mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Build + validate the resolver/DB pool and rehydrate the transparency log now, not on first
    # request, so a misconfigured database fails the deploy loudly.
    get_resolver()
    get_audio_resolver()
    get_video_resolver()
    get_log()
    # Seed the credential-free demo assets when asked (VERIDEX_DEMO_SEED=1), so a live deploy with no
    # provider key still shows a real VERIFIED recovery. The image, audio, and video assets use
    # separate resolvers (no cross-modal matches) but share the transparency log + B2. Idempotent.
    if os.environ.get("VERIDEX_DEMO_SEED") == "1":
        seed_demo(get_resolver(), get_log(), get_storage())
        seed_audio_demo(get_audio_resolver(), get_log(), get_storage())
        seed_video_demo(get_video_resolver(), get_log(), get_storage())
        # The multi-provider image demos share the image resolver + the transparency log + B2.
        seed_providers(get_resolver(), get_log(), get_storage())
    # Seal the current signed tree head to the Object-Lock bucket (B2_BUCKET_LOCKED), so the
    # immutable audit anchor exists before any reader asks. After any seeding, so it captures the
    # seeded tree size. Best-effort and only acts when a locked bucket is configured: a missing
    # capability never fails the deploy (the surface degrades to the labeled in-memory model).
    seal_startup_checkpoint()
    # Wire the mounted MCP server's tools to THIS app's SBR routes through an in-process ASGI
    # client: no network hop and no credentials, the same path the test suite uses. So /mcp and the
    # front end consume the exact same vendor-neutral API.
    mcp_client = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://rooted-internal", timeout=30.0
    )
    mcp_server.set_client(mcp_server.SbrClient(mcp_client))
    try:
        yield
    finally:
        # Close the connection pools on shutdown (a no-op for the in-memory backends).
        await mcp_client.aclose()
        mcp_server.set_client(None)
        get_resolver().close()
        get_audio_resolver().close()
        get_video_resolver().close()
        get_log().close()


def create_app(*, mount_mcp: bool = True) -> FastAPI:
    """Build the Rooted SBR API. mount_mcp mounts Rooted's MCP server at /mcp (the default); set it
    False for the schemathesis contract test, whose ASGI transport cannot run the MCP session
    manager's lifespan. The SBR routes, and therefore the OpenAPI surface, are identical either way.
    """
    app_lifespan: Lifespan[FastAPI]
    if mount_mcp:
        # path="/" because it is mounted at /mcp below, so the MCP endpoint is /mcp. Its lifespan
        # (the streamable-HTTP session manager) must run, so it is combined with the app lifespan.
        mcp_app = mcp_server.mcp.http_app(path="/")
        app_lifespan = combine_lifespans(lifespan, mcp_app.lifespan)
    else:
        app_lifespan = lifespan

    app = FastAPI(title="Veridex SBR API", version="0.1.0", lifespan=app_lifespan)
    # Reject an over-cap request body before it is buffered, so an unauthenticated upload to the
    # public recovery endpoints cannot exhaust disk/RAM on the live instance. The per-endpoint asset
    # caps in sbr.py remain as a second line of defense.
    app.add_middleware(LimitRequestBodyMiddleware)
    app.include_router(sbr_router)
    app.include_router(demo_router)
    app.include_router(generate_router)
    app.include_router(status_router)
    app.include_router(agent_router)
    app.include_router(lineage_router)
    app.include_router(checkpoint_router)
    app.include_router(genblaze_router)
    app.include_router(genblaze_verify_router)
    app.include_router(tamper_router)
    app.include_router(transcript_router)
    app.include_router(b2_events_router)
    app.include_router(byo_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe. Returns no provenance data, safe for an unauthenticated check."""
        return {"status": "ok", "service": "veridex-api"}

    if mount_mcp:
        # Mount Rooted's MCP server in-process so the curated provenance tools are reachable at /mcp
        # on the same deploy (no separate service). Mounting is independent of the OpenAPI surface,
        # so /mcp stays out of the spec-defined SBR contract and the schemathesis run.
        app.mount("/mcp", mcp_app)
    return app


app = create_app()
