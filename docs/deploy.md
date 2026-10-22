# Deploy

Veridex runs as two services: the FastAPI SBR API on Render and the Next.js front end on Vercel. The
demo runs fully in-memory (no Postgres, Redis, B2, or provider keys), so the live, judge-facing site
needs no credentials: the seeded demo asset makes it show a real VERIFIED recovery.

Live:
- Front end: YOUR_VERIDEX_SITE_URL
- API: YOUR_VERIDEX_API_URL

## API (Render)

Render's native Python runtime (NOT Docker) builds and runs the API; config is in `render.yaml`:

- Runtime: `python`, plan `starter` (paid, always-on, no cold start), region `virginia`, autoDeploy
  on `main`, health check `/health`.
- Build: `pip install uv && uv sync --locked --package veridex-api --no-dev` (only the API package and
  its workspace deps, so no worker/Genblaze/torch).
- Start: `.venv/bin/uvicorn veridex_api.main:app --host 0.0.0.0 --port $PORT`.
- Env: `VERIDEX_DEMO_SEED=1` (seeds the demo asset so recovery returns VERIFIED live);
  `PYTHON_VERSION=3.12.7`.

Deploy via the Render Blueprint (`render.yaml`) or create a native Python web service pointed at the
repo with those build/start commands. (The Render API/MCP cannot create Docker services, so the
native runtime is the deploy path; there is no Dockerfile.)

Optional production hardening (not needed for the demo): `DATABASE_URL` for Postgres-backed recovery +
a persistent transparency log; `VERIDEX_REAL_WATERMARK=1` plus the `watermark` extra for real TrustMark
(pulls torch); the B2 / provider keys for real ingest (`B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET_DEV`);
`VERIDEX_INGEST_KEY` to gate `POST /ingest` (the `X-Ingest-Key` header).

### Stable checkpoint key (recommended for the judging window)

By default the checkpoint signing key is ephemeral, so each redeploy generates a new key and
invalidates inclusion proofs handed out earlier. To keep the public key and all proofs stable across
redeploys, set `ED25519_PRIVATE_KEY_HEX` to the raw Ed25519 key as a single hex line (a Render Secret
Files mount at a path + `ED25519_PRIVATE_KEY_PATH` also works). Generate one with:

```bash
uv run python -c "from veridex_provenance.signing import generate_keypair, private_key_bytes, public_key_bytes as P; k,p=generate_keypair(); print('HEX', private_key_bytes(k).hex()); print('PUB', P(p).hex())"
```

Set `ED25519_PRIVATE_KEY_HEX` (secret) in the dashboard, redeploy, and confirm
`GET /transparency/checkpoint` reports `keySource: "configured"` with the matching `publicKeyHex`.

## Front end (Vercel)

Deployed to the dedicated `veridex-web` project (via the Vercel CLI from `web/`, which makes `web/` the
project root). `web/vercel.json` pins `framework: nextjs`.

- Env: `API_PROXY_TARGET` = the Render API URL. `next.config.ts` rewrites `/api/*` to it, so the
  browser talks to the API same-origin (no CORS). Leave `NEXT_PUBLIC_API_BASE_URL` unset.
- Redeploy: `cd web && vercel deploy --prod -b API_PROXY_TARGET=<render-url> -e API_PROXY_TARGET=<render-url>`.

## Keepalive

`.github/workflows/keepalive.yml` pings the API `/health` (and the site) every 10 minutes and fails
loudly if either is down. The repo variables `VERIDEX_API_URL` and `VERIDEX_SITE_URL` are set to the
live URLs above; `starter` does not spin down, so this is insurance plus a visible signal.

## Verify after deploy

1. `curl https://<api>/health` returns `{"status":"ok"}`.
2. `curl https://<api>/transparency/log` returns the seeded leaves (treeSize 7) and a root hash.
3. Open the site, click "recover the demo asset" -> VERIFIED with the signed manifest, the Content
   Credentials panel reads the credentialed sample, and the Merkle explorer renders the tree.
