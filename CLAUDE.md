# CLAUDE.md

This file orients Claude Code to the Veridex repo. It is always loaded, so it holds standing facts
only: what the project is, how the repo is laid out, the commands to build and test each service,
the stack and its pinned versions, the MCP servers in use, and the conventions to follow. Repeatable
procedures live in `.claude/skills/`, not here, to keep per-turn context small. Deep planning and
strategy live in the local (gitignored) `research/` folder and in Claude memory, never in this file.

---

## What Veridex is

Veridex is an open-source, vendor-neutral C2PA Soft Binding Resolution (SBR) server backed by
Backblaze B2. It recovers stripped C2PA provenance manifests for AI-generated media. The core flow:
an image is generated and signed, then later shows up stripped of its embedded manifest (for example
after a screenshot or re-encode), and Veridex recovers the full provenance by matching an invisible
watermark or a perceptual-hash fingerprint against manifests stored in B2, then returns the
recovered, signed manifest with a tamper-evident transparency-log proof.

The pipeline, end to end:
generate (Genblaze, multi-provider) -> store asset + SHA-256 manifest to B2 -> embed TrustMark
variant P watermark -> compute PDQ perceptual hash (internal index) -> sign manifest (Ed25519/COSE)
and map to a C2PA claim (c2pa-python) -> serve the vendor-neutral SBR API backed by B2 -> apply the
SB 942-style PII-redaction layer (output system provenance, withhold personal provenance) -> append
to a Merkle transparency log with signed checkpoints written to B2 under Object Lock.

Veridex also exposes its own MCP server as a product feature, so AI agents can verify provenance,
recover manifests, and query the transparency log conversationally.

---

## Project context

Built for the Backblaze Generative Media Hackathon (Devpost). Submission deadline August 3 2026,
5pm ET; judging through the August 12 winners announcement. The build optimizes for four dimensions:
real-world utility, production readiness, meaningful use of Backblaze B2 storage and data
orchestration, and meaningful use of Genblaze. Two engineering decision points gate the build and
must clear early:

- The watermark kill experiment: whether TrustMark variant P survives a real full-frame screenshot.
  If it does, the demo recovers from a live screenshot; if not, the same architecture recovers from
  re-encode or re-upload (the PDQ fallback closes the loop either way). This decides the narration,
  not whether the product works.
- The validatable core: the recovery loop must close on real data. The image loop is the core and is
  built and verified first; audio, video, the full transparency-log UI, and the cinematic front end
  are additive layers on top of the working core (loop before beauty).

---

## Repo layout

Monorepo: Turborepo for the JS side, uv workspaces for the Python side.

```
/web          Next.js 15 App Router front end (React 19, TypeScript, Tailwind v4, shadcn/ui)
/api          FastAPI backend: the SBR API endpoints, signing, redaction
/worker       the generate -> watermark -> fingerprint -> sign -> log pipeline + Genblaze generator (the live ingest runs in-process in /api)
/packages
  /provenance c2pa-python, TrustMark, PDQ, Ed25519/COSE, Merkle-log logic (the trust core)
  /storage    Backblaze B2 access (b2sdk) and the Genblaze sink wiring
/mcp          Veridex's own MCP server (FastMCP, wraps the SBR API as curated tools)
/docs         architecture, ADRs, the demo runbook
```

`research/` is local-only (gitignored): strategy, the design references, the nk.studio crawl.

---

## Stack and pinned versions

Verify every version via Context7 before generating code; the numbers below are the intended targets.

- Python 3.11-3.13, uv workspace. FastAPI 0.135+, Pydantic v2, Uvicorn, sse-starlette. Generation
  runs in-process in the API (no task queue). No ORM/migrations: the Postgres index uses sync psycopg
  + psycopg-pool with raw SQL (native `bit(256)` + `bit_count`).
- Storage and provenance: b2sdk, c2pa-python 0.32.x, trustmark (variant P), pdqhash, cryptography
  (Ed25519), pycose (COSE_Sign1), pymerkle.
- Database: Postgres 16 + pgvector 0.8.1 (minimum 0.7.0 for the `bit` type and `bit_hamming_ops`).
- MCP product surface: FastMCP.
- Front end: Next.js 15, React 19, Tailwind v4, shadcn/ui, Motion, GSAP 3.13, Lenis, three.js +
  @react-three/fiber + @react-three/drei + @react-three/postprocessing, react-force-graph,
  @contentauth/c2pa-web, openapi-typescript + openapi-fetch + TanStack Query.

---

## Commands

Python services use `uv`. The JS front end uses `pnpm` (locked).

Backend / worker / packages (from repo root or the relevant service dir):
- Install: `uv sync --locked --all-extras --dev`
- Run the API: `uv run fastapi dev api/main.py` (the ingest pipeline runs in-process)
- Lint: `uv run ruff check .`  Format: `uv run ruff format .` (CI: `uv run ruff format --check .`)
- Type-check: `uv run mypy .` (and/or `uv run ty check` for fast local feedback)
- Test: `uv run pytest`
- Contract-test the SBR API: `uvx schemathesis run http://localhost:8000/openapi.json --checks all`

Front end (from `/web`):
- Install: `pnpm install`   Dev: `pnpm dev`   Build: `pnpm build`   Lint: `pnpm lint`
- Component tests: `pnpm test` (Vitest + React Testing Library)
- Regenerate the typed API client: `pnpm generate:api`
  (openapi-typescript + openapi-fetch against `/openapi.json`)

Local full stack:
- `docker compose up` brings up Postgres (pgvector/pgvector:pg16) for local Postgres-backed runs.

Always run lint, type-check, and tests before considering a change done. Never commit a change that
leaves `uv.lock` stale (CI runs `uv sync --locked` and will fail).

---

## MCP servers in use

Use these rather than guessing or reaching for the browser:

- context7 (remote) - live, version-specific docs. ALWAYS use Context7 for library or API docs before
  generating code against any dependency. This is the highest-leverage rule in this file.
- github (remote) - issues, PRs, repo operations, CI status.
- postgres - Crystal DBA `postgres-mcp` (Postgres MCP Pro) in `--access-mode=restricted`. Schema
  inspection, safe queries, pgvector index tuning. Do NOT install
  `@modelcontextprotocol/server-postgres` (deprecated, unpatched SQL injection in its read-only path).
- vercel (remote) - front-end deploys and logs.   render (remote) - backend deploys, logs, env.
- playwright (local) - E2E tests and the scripted demo run.   serena (local) - symbol navigation.
- sequential-thinking, memory (local).   Optional: figma, magic, stitch for UI; sentry for triage.

Backblaze B2 has no official MCP server. Access B2 in code via `b2sdk` (or boto3 against the
S3-compatible endpoint), and use Backblaze's official Claude Agent Skill for B2 management tasks.

---

## CLIs available

`uv`, `ruff`, `pytest`, `schemathesis`, `pnpm`, `vercel`, `render`, `modal`, `b2`, `gh`, `git`.
Prefer these for deploys, logs, and secrets over manual steps.

---

## Deployment

- Front end: Vercel. Typed from the backend `/openapi.json`; `/api/*` proxied via `next.config.js`
  rewrites (or CORS enabled for the Vercel origin).
- API + Postgres: Render, paid always-on instance to avoid cold starts on stage.
- GPU / slow tail (TrustMark encode): Modal serverless, weights pre-baked into the image.
- B2 buckets: a dev bucket with no Object Lock retention for iteration, and a separate locked bucket
  (compliance retention) for the final verified run and the demo only. Object Lock writes are
  immutable, so never iterate against the locked bucket.
- Keep the live app and its database funded and warm from submission through the judging window;
  judges click the link days later. A scheduled keepalive ping that fails loudly is worth it.

Secrets live in GitHub Actions secrets, Vercel env, Render env, and Modal secrets, with a single
`.env.example` as the placeholder template. Never commit secrets and never hardcode them in
`.mcp.json` (use `${ENV_VAR}` interpolation). Required external credentials: B2 application key
(B2_KEY_ID / B2_APP_KEY), the generation-provider keys (for example GMI Cloud, OpenAI), and the
platform tokens (Vercel, Render, Modal). These are expected, not extra dependencies.

---

## Conventions and build rules

- Style: plain, direct prose in docs and comments. No marketing language. No em-dashes anywhere (a
  deliberate house rule; use commas, parentheses, or separate sentences). Avoid the AI-tone blocklist
  (leverage, seamless, robust, comprehensive, unlock, delve, elevate, empower, and similar).
- TypeScript: end-to-end type safety against the FastAPI backend via generated clients
  (openapi-typescript + openapi-fetch + TanStack Query). Regenerate types whenever the API changes;
  never hand-write API response types the schema can produce.
- Python: FastAPI + Pydantic v2, async-first. The Postgres index uses sync psycopg + psycopg-pool with
  raw SQL (no ORM, no migrations); blocking calls are offloaded via run_in_threadpool. Validate
  everything at the boundary.
- Perceptual-hash search: store PDQ hashes as `bit(256)` in Postgres, index with an HNSW
  `bit_hamming_ops` index (pgvector 0.7+), query by Hamming distance (threshold 31). Watermark-ID
  lookups are exact-match (a plain B-tree index), not nearest-neighbor. PDQ is an internal index
  only; never advertise it on `/services/supportedAlgorithms` (it is not a registered C2PA algorithm).
- C2PA signing requires an X.509 certificate chain, not a bare key. A self-signed test cert shows
  "Valid," not the green "Trusted" state (green needs a Conformance-Program CA). Show this honestly;
  demo the green path via the C2PA conformance test mode, labeled on screen as test mode.
- TrustMark: standardize on variant P everywhere. Pre-bake the model weights into the container (they
  download on first use otherwise, which fails offline). Never double-watermark an image.
- The product UI stays generic and universal: no hardcoded persona names or company names in the
  build. Named examples belong only in live pitch narration, never in the shipped interface.
- Honesty rule, surfaced in the UI: provenance proves origin, not truth.

### Always-on engineering discipline
- Read (the Read tool) before any Edit or Write on a file; Bash inspection does not count.
- Lint + type-check + test clean before every commit. Atomic commits (one logical change),
  Conventional Commits, subject <= 100 chars, a Co-Authored-By trailer, branch-first, push after each.
- CI is the gate: after a merge, watch the post-merge main run per job, match its headSha to the
  merged SHA (or read the commit's check-runs API), and require every check to be success. A single
  `--watch` exit code is not proof of green.
- No fiction and no synthetic data on the load-bearing path; every named tool, model, and integration
  is wired end to end or the claim is cut. Numbers are identical across the repo, the docs, and any
  submission, taken from the actual test suite and metrics.
- Never commit secrets; scan the full git history before the repo goes public; third-party PII and
  internal strategy stay in local `research/` or Claude memory.

---

## Testing and quality

- Python: pytest + pytest-asyncio + httpx for the API.
- Contract: schemathesis against the SBR OpenAPI spec, proving the API conforms to the C2PA SBR
  contract. High value because the SBR API is spec-defined; run it in CI.
- Front end: Vitest + React Testing Library for components; Playwright for E2E and visual regression
  (screenshot diffs on a fixed viewport for the WebGL/3D surfaces), one assertion per visible surface.
- Demo-safety: a k6 or locust smoke test against the SBR endpoints and the perceptual-hash search
  before deploy, so the live demo will not fall over.

---

## How to work in this repo

- Use plan mode for any change that touches more than one service; let an Explore subagent map the
  relevant code first so the main context stays small.
- Use subagents to build independent pieces in parallel (for example the react-three-fiber scene and
  the FastAPI SBR endpoints), each spec'd fully since they start cold, and each including the
  build-and-verify step. Honesty-gate every agent and verify its findings against the source.
- Keep repeatable procedures (deploy runbook, release checklist, the schemathesis run, the demo-run
  script) in `.claude/skills/`, not in this file.
- When uncertain about a dependency, fetch the fact via Context7 or read the actual repo. Do not
  generate code against a remembered API surface for a fast-moving dependency (react-three-fiber,
  FastMCP, c2pa-python, Genblaze).

---

## Genblaze integration note

Genblaze emits its own SHA-256-bound JSON provenance manifest, NOT a C2PA manifest (its own docs say
to pair it with your own signer or C2PA when adversarial verification matters). Only its Mode 1
(integrity) ships today; signing (Mode 2) and C2PA interop (Mode 3) are on the roadmap and are not
implemented, so Veridex's own Ed25519/COSE signing and c2pa-python claim mapping are load-bearing, not
redundant. Treat the Genblaze manifest as complementary input and keep c2pa-python as the
authoritative C2PA layer. Install-name gotcha: `pip install genblaze` pulls `genblaze-core` +
`genblaze-s3`, and imports use underscores (`import genblaze_core`). Genblaze is a young alpha SDK
(v0.3.2); pin the version and expect API churn. Do not use `chat()` as a Pipeline provider (known
asymmetry). Asset SHA-256 is computed before embedding, so keep originals in B2 to verify.
