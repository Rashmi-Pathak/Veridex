# VERIDEX

**Recover stripped C2PA provenance for AI-generated media, on Backblaze B2.**

[![CI](https://github.com/StephenSook/veridex/actions/workflows/ci.yml/badge.svg)](https://github.com/StephenSook/veridex/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Live demo](https://img.shields.io/badge/live-demo-34d399.svg)](YOUR_VERIDEX_SITE_URL)
[![PyPI](https://img.shields.io/pypi/v/veridex-sbr.svg?logo=pypi&logoColor=white)](https://pypi.org/project/veridex-sbr/)
[![Python](https://img.shields.io/badge/python-3.11--3.13-3776AB.svg?logo=python&logoColor=white)](./pyproject.toml)
[![Next.js](https://img.shields.io/badge/Next.js-15-black.svg?logo=nextdotjs)](./web)
[![C2PA SBR](https://img.shields.io/badge/C2PA-SBR_2.4-6366f1.svg)](https://spec.c2pa.org/specifications/specifications/2.4/softbinding/Decoupled.html)

Veridex is an open-source, vendor-neutral C2PA Soft Binding Resolution (SBR) server. When an image,
audio clip, or video is generated and signed, then later shows up with its embedded C2PA manifest
destroyed (after a screenshot or a re-encode), Veridex recovers the full provenance by matching an
invisible watermark or a perceptual-hash fingerprint against manifests stored in Backblaze B2, and
returns the recovered, signed manifest with a tamper-evident transparency-log proof.

Backblaze B2 is the recovery repository the whole system depends on, not an add-on. Every signed
asset, manifest, and COSE signature is addressed by its content hash on B2, so recovery returns
exactly the bytes that were signed, and the Merkle transparency checkpoints seal to a B2 Object Lock
bucket under compliance retention, immutable by construction. An SBR server is only as good as the
durable, vendor-neutral repository it recovers from, and that repository is B2.

## Live demo

| Surface | Where |
|---|---|
| Web | <YOUR_VERIDEX_SITE_URL> (installable PWA: Add to Home Screen) |
| SBR API | <YOUR_VERIDEX_API_URL> |
| MCP server | `YOUR_VERIDEX_API_URL/mcp` (judge-connectable over HTTP) |
| CLI | `pip install veridex-sbr`, then `veridex recover stripped.jpg` ([PyPI](https://pypi.org/project/veridex-sbr/)) |
| Browser extension | load `extension/` unpacked (see [extension/README.md](./extension/README.md)) |
| Android app | [APK release](https://github.com/StephenSook/veridex/releases/tag/mobile-v0.1.0): share any image to Veridex Verify and it recovers against the live registry ([mobile/android](./mobile/android)) |
| iOS app | [TestFlight beta](https://testflight.apple.com/join/X3T8nHza): native SwiftUI verifier, pick or share an image and it recovers against the live registry ([mobile/ios](./mobile/ios)) |

The site opens on a bloomed galaxy hero with a live `/status` metrics ribbon: the transparency tree,
the recovery self-test latency and similarity, the storage backend, the recovery index, and the
generation state, all read live. The lead visual then performs the thesis on one real image: a
C2PA-credentialed sample is stripped in the browser by a genuine JPEG re-encode (which drops the
embedded manifest), and Veridex recovers the provenance to **VERIFIED** with a live SBR API call (the
result is the real registry response, never hardcoded). Below that, a sticky scroll-spy nav runs over
six acts: the recovery loop, every modality, standards-grade trust, Backblaze B2, the transparency
log, and the open network. Along the way a real AI-generated image (created with Genblaze on GMI
Cloud, model seedream-5.0-lite) recovers to VERIFIED with the recovered manifest naming that model, a
separately C2PA-credentialed sample is read in the browser to show its Content Credentials, and the
transparency log renders as a 3D Merkle tree. The deployed instance stores each asset, manifest, and
signature content-addressably on Backblaze B2 (verifiable live at `/demo/storage`) and runs recovery
on Postgres + HNSW (`recoveryIndex: postgres+hnsw`). Provenance proves origin, not truth.

## The problem

Fewer than 1% of images published online carry C2PA metadata, and embedded manifests are routinely
stripped by social platforms and re-encodes. C2PA's answer is durable recovery: recover the stripped
manifest from a repository using a watermark or a fingerprint. The reference production
manifest-recovery service today is Adobe's Content Credentials Cloud, and it is a closed,
single-vendor hosted service. Veridex is the open, self-hostable, vendor-neutral version, on commodity
object storage you control, across image, audio, and video, with a WORM transparency log and an MCP
surface for AI agents.

## What it does

1. **Generate and sign.** A provider generates media; Veridex watermarks it (TrustMark variant P),
   computes a PDQ perceptual hash, signs the manifest (Ed25519 / COSE), maps it to a C2PA claim, and
   stores the asset, manifest, and signature on Backblaze B2.
2. **Index and log.** The watermark id and the PDQ `bit(256)` hash go into the recovery index
   (Postgres + pgvector HNSW), and the manifest's canonical hash is appended to a Merkle transparency
   log whose signed checkpoints seal to a B2 Object Lock bucket.
3. **Recover.** The asset circulates and loses its manifest. Given the stripped bytes, the SBR API
   tries the watermark (an exact pointer) first, then falls back to the PDQ fingerprint (nearest
   within Hamming distance 31), returns the recovered signed manifest with a SB 942 redaction split
   (system provenance out, personal provenance withheld), and an inclusion proof pinned to a signed
   checkpoint.

## Veridex in one loop

```mermaid
flowchart LR
    G["Generate<br/>(Genblaze, multi-provider)"] --> W["Watermark<br/>(TrustMark variant P)"]
    W --> S["Store to Backblaze B2<br/>(content-addressable)"]
    S --> SG["Sign<br/>(Ed25519 / COSE + C2PA claim)"]
    SG --> IDX["Index for recovery<br/>(watermark id + PDQ bit(256))"]
    IDX --> L["Append to Merkle log<br/>(signed checkpoints, B2 Object Lock)"]
    STRIP["Asset circulates,<br/>manifest stripped"] -. "screenshot / re-encode" .-> R
    L --> R["SBR API recovery<br/>watermark, then PDQ fallback"]
    R --> RED["Redact (SB 942 split)<br/>system out, personal withheld"]
    RED --> V["VERIFIED + inclusion proof<br/>pinned to a signed checkpoint"]
```

## Architecture

Many client surfaces (web, native iOS + Android, CLI, MCP, browser extension, an embeddable badge)
over one trust core over two stores. Backblaze B2 holds the durable, content-addressed record and
the WORM transparency seal; Postgres holds the fast recovery index. A dedicated Modal service
carries the TrustMark model so the lean API stays torch-free.

```mermaid
flowchart TB
    subgraph Surfaces
        WEB["Web<br/>Next 15 + R3F"]
        API["SBR API<br/>FastAPI"]
        MCP["MCP server<br/>FastMCP"]
        CLI["CLI<br/>veridex-sbr"]
        EXT["Browser extension<br/>MV3"]
        MOB["Native apps<br/>iOS + Android"]
    end
    subgraph Model["Model service"]
        WM["TrustMark<br/>watermark (Modal)"]
    end
    subgraph Core["Trust core (packages/provenance)"]
        RES["Resolver<br/>watermark + PDQ"]
        SIGN["Signer<br/>Ed25519/COSE + C2PA claim"]
        LOG["Merkle transparency log"]
    end
    subgraph Stores
        B2[("Backblaze B2<br/>assets · manifests · signatures<br/>WORM checkpoints")]
        PG[("Postgres + pgvector<br/>bit(256) HNSW index")]
    end
    WEB --> API
    CLI --> API
    EXT --> API
    MOB --> API
    API --> MCP
    API --> WM
    API --> RES --> SIGN --> LOG
    RES --> PG
    SIGN --> B2
    LOG --> B2
    B2 -. "event webhook (pending Backblaze tier)" .-> API
```

## What is real (capability honesty)

Everything below is wired end to end and demonstrable. Numbers in any submission come from the test
suite, never from draft prose.

| Area | State |
|---|---|
| SBR recovery loop (watermark, then PDQ fallback), C2PA v2.4 routes, camelCase per the spec | wired, tested, live |
| Backblaze B2 as the recovery repository (content-addressed assets / manifests / signatures) | wired + live |
| Merkle transparency log + signed checkpoints, sealed to a B2 Object Lock (WORM) bucket, read back + verified | wired + live |
| Postgres + pgvector HNSW `bit(256)` recovery index, selected by `DATABASE_URL` | wired + live (`recoveryIndex: postgres+hnsw`) |
| Real Genblaze generation (GMICloud primary, OpenAI fallback) | wired + demonstrated: the live demo recovers a real GMICloud generation |
| Genblaze AssemblyAI speech-to-text: a real speech clip to a hash-verified transcript, reconciled live with Veridex's signature (the run was persisted to B2; its object keys are recorded) | wired + live |
| Genblaze wrote its own run to B2 via its `ObjectStorageSink` (a prior run); the endpoint reconciles the integrity hash + Veridex's signature live | wired + live |
| Genblaze v0.6.0 byte-level output verification (`genblaze verify --fetch`): the asset is fetched from Backblaze B2 with a presigned GET and its bytes re-hashed against the manifest's committed sha256, on top of genblaze-core's Mode 1 manifest verification | wired + live (`/demo/genblaze-verify`, `byteSource: b2`) |
| Multi-provider recovery (Nano Banana 2 / Flux 2 Pro / Qwen via kie.ai), vendor-neutral | wired + live |
| TrustMark variant P watermark + PDQ fallback; the real embed/decode runs live via a dedicated Modal model service, so the ReMark watermark-removal failover shows a real decode defeated while PDQ still recovers | wired + live |
| Audio + video modalities (spectral audio fingerprint, per-keyframe video PDQ) | wired + live |
| Green C2PA "Trusted" via the conformance test trust list (labeled FOR TESTING ONLY) | wired + live |
| C2PA ingredient-DAG lineage + a 3D graph; tamper-diff forensics (which signed field changed vs the registry) | wired + live |
| Side-by-side vs the official C2PA reader (No Content Credentials vs RECOVERED on the same bytes) | wired + live |
| FastMCP product server (judge-connectable over HTTP); a Claude provenance agent, opt-in when `ANTHROPIC_API_KEY` is set | wired + live |
| Packaged `veridex` SBR CLI, published on PyPI (`pip install veridex-sbr`) | wired + live |
| Browser extension (right-click any image to recover its provenance) | wired (load unpacked) |
| Native iOS (SwiftUI) + Android (Compose) verifier apps: pick / photograph / share an image to recover against the live registry, same verify path, no mock data | wired + live (Android APK release; iOS on TestFlight) |
| Embeddable verify badge: a one-line script that renders a live provenance seal on any third-party site | wired + live |
| Act-based web UI: a bloomed galaxy hero, a live `/status` metrics ribbon, the in-browser strip-and-recover reveal, and a sticky scroll-spy nav over six acts | wired + live |
| Append-only Merkle consistency proof, bound to the WORM B2 checkpoint (`sealedInObjectLock`, `sealedRootMatches`) | wired + live |
| Checkpoint-history: the chain of signed checkpoints, each re-verified with its own immutable retain-until (lists the real WORM objects when the locked bucket is list-readable, labeled when it falls back to the model) | wired + live |
| Nuke-and-rebuild: rebuild the recovery index from B2 content-addressed objects alone (no database), then re-prove recovery (`demoRecovered`, similarity 100) | wired + live |
| Adversarial robustness grid: which transforms a recovery survives (JPEG re-encode, downscale, upscale, and a screenshot recover; crop and rotation do not) | wired + live |
| Federated SBR peer-forward across an open, vendor-neutral network (`VERIDEX_SBR_PEERS`), advertised on the SBR surface | wired (no peers configured on the live instance) |
| Shareable provenance-receipt permalink `/r/<manifestId>` (provenance, inclusion proof, VERIFIED badge, citable) | wired + live |
| B2 Event-Notification ingest (a B2 upload posts a signed webhook; Veridex verifies the HMAC, fetches from B2, registers, and the asset becomes recoverable) | wired and tested; native delivery pending Backblaze's enterprise Event Notifications tier; the webhook, B2 fetch, ingest, and recovery are downstream-verified |

## The surfaces

- **Web** (`/web`): a Next.js 15 front end. A bloomed galaxy hero with a live `/status` metrics ribbon,
  the in-browser strip-and-recover reveal as the lead visual, and a sticky scroll-spy nav over six acts
  (the recovery loop, modalities, trust, Backblaze B2, the transparency log, the open network). Inside:
  the side-by-side vs the official C2PA reader, the Content Credentials panel (c2pa-web), a 3D Merkle
  explorer, the consistency, checkpoint-history, rebuild, robustness, and federation panels, and a
  shareable provenance-receipt permalink at `/r/<manifestId>`.
- **SBR API** (`/api`): the C2PA v2.4 Soft Binding Resolution routes, signing, the SB 942 redaction,
  the transparency routes, and the B2 event-ingest webhook.
- **MCP server** (`/mcp` and mounted at `/mcp` on the API): three curated tools so an AI agent can
  verify provenance, recover manifests, and query the transparency log conversationally.
- **CLI** (`/cli`): the `veridex` command (`recover`, `status`, `manifest`, `proof`, `algorithms`)
  wrapping the public SBR API; install with `pip install veridex-sbr`.
- **Browser extension** (`/extension`): a Manifest V3 extension that recovers provenance for any image
  on the web from a right-click.
- **Mobile apps** (`/mobile`): a native SwiftUI iOS app (with a "Verify with Veridex" share extension)
  and a native Jetpack Compose Android app (a system share-sheet target plus camera capture). Pick,
  photograph, or share any image and it recovers against the live registry, showing the recovered
  manifest and the Merkle proof. The Android build ships as an installable APK release; the same
  verify code path runs live against the deployed API, with no mock data.
- **Verify badge** (`/web/public/badge.js`): a one-line `<script>` any site can paste to show a live
  provenance seal for a manifest, served from a CORS-open route so it embeds anywhere.
- **B2 event ingest**: a Backblaze B2 Event Notification rule posts a signed webhook when an object
  lands under a watched prefix; Veridex verifies the HMAC, fetches the object, and registers it for
  recovery. Once the rule is enabled, dropping an asset in B2 makes it auto-recoverable.

## SBR API

Real C2PA v2.4 Soft Binding Resolution routes, contract-tested with schemathesis against
`/openapi.json`:

- `GET /services/supportedAlgorithms` (PDQ is an internal index, never advertised)
- `POST /matches/byContent`, `GET /matches/byBinding` to `{matches: [{manifestId, similarityScore?}]}`
- `GET /manifests/{id}` (redacted: system provenance out, personal provenance withheld)
- `GET /transparency/checkpoint`, `GET /transparency/proof/{id}` (proof pinned to a signed checkpoint)
- `POST /ingest` (trusted generation-side; gated by `VERIDEX_INGEST_KEY`, required in production)

## Tech stack

- **Backend**: Python 3.11 to 3.13, FastAPI + Pydantic v2 (async-first), `uv` workspace. In-process
  generation, no task queue. Postgres index via sync psycopg + raw SQL (no ORM, no migrations).
- **Provenance**: c2pa-python, TrustMark (variant P), pdqhash, cryptography (Ed25519), pycose
  (COSE_Sign1), pymerkle.
- **Storage / data**: Backblaze B2 (b2sdk), Postgres 16 + pgvector 0.8 (HNSW `bit_hamming_ops`).
- **Front end**: Next.js 15, React 19, Tailwind v4, three.js + react-three-fiber, react-force-graph,
  @contentauth/c2pa-web, openapi-typescript + openapi-fetch + TanStack Query.
- **MCP**: FastMCP. **CLI**: typer + httpx. **Extension**: Manifest V3 (no build step).

## Repo layout

```
/api          FastAPI SBR API (C2PA v2.4 routes), signing, SB 942 redaction, transparency, B2 event webhook
/worker       the generate -> watermark -> store -> sign -> index -> log ingest pipeline + Genblaze generator
/mcp          Veridex's own MCP server (FastMCP): verify_asset, recover_manifest, query_transparency_log
/cli          the `veridex` SBR CLI (veridex-sbr, published on PyPI)
/extension    Manifest V3 browser extension: right-click any image to recover its provenance
/mobile
  /ios        native SwiftUI verifier + share extension (pick / photograph / share an image to verify)
  /android    native Jetpack Compose verifier (share-sheet target + camera), published as an APK release
/infra
  /modal      the TrustMark watermark model service (real embed + decode over HTTP, weights baked)
/packages
  /provenance trust core: models + canonical hashing, Ed25519/COSE, c2pa-python claim, PDQ, Merkle log
  /storage    Backblaze B2 (b2sdk), PostgresIndex (pgvector bit(256) HNSW), transparency store
/web          Next.js 15 front end: R3F galaxy, recovery reveal, C2PA display, 3D Merkle explorer, verify badge
/scripts      one-shot ops (B2 Object Lock, event-rule + CORS + lifecycle + SSE configurators, Modal + PyPI publish)
```

## Quickstart

```bash
cp .env.example .env                       # fill real values (B2, provider keys, platform tokens)
uv sync --locked --all-packages --dev      # backend deps
uv run fastapi dev api/main.py             # the SBR API on :8000 (ingest runs in-process)
cd web && pnpm install && pnpm dev         # the front end
```

`DATABASE_URL` selects the Postgres index (live recovery on Postgres + HNSW); unset, Veridex runs on an
in-memory index so the demo needs no database. `docker compose up` brings up Postgres (pgvector) for
local Postgres-backed runs.

## Verification

```bash
uv run ruff check . && uv run ruff format --check .   # CI gates on these
uv run mypy .                                         # strict; CI gates on this too
uv run pytest                                         # incl. real-Postgres tests via pgserver
uvx schemathesis run http://localhost:8000/openapi.json --checks all   # SBR contract
cd web && pnpm test                                  # front-end component tests (Vitest + RTL), CI gate
cd web && pnpm test:e2e                               # Playwright E2E vs the live (or E2E_BASE_URL) stack
```

The Playwright E2E drives the real recovery flow end to end (front end to the `/api` proxy to SBR
recovery) against the deployed site by default. A load smoke against the SBR read endpoints held 0
failures at p95 around 6 ms, so the live demo holds up under concurrent judges.

## Deploy

- **Front end**: Vercel (`veridex-web`), typed from the backend `/openapi.json`, `/api/*` proxied to the
  API.
- **API + Postgres**: Render (`veridex-api`, always-on) + a managed Postgres.
- **B2 buckets**: a dev bucket for iteration and a separate Object Lock (compliance retention) bucket
  for the WORM transparency seal.
- **Watermark model**: a Modal service (`infra/modal`) carrying the real TrustMark model, so the API
  container stays torch-free; wired in via `VERIDEX_WATERMARK_REMOTE_URL`.
- **Mobile**: the Android app ships as a GitHub APK release; the iOS app is distributed through
  TestFlight (public link, Apple beta review cleared).

A scheduled keepalive ping keeps the live app and database warm through the judging window.

## Honesty and limitations

- Provenance proves origin, not truth. A self-signed credential shows "Valid," not the green
  "Trusted" state, which needs a Conformance-Program CA. Veridex shows the green "Trusted" state by
  validating against the C2PA conformance test trust list, labeled FOR TESTING ONLY on screen; a
  production deployment validates against the C2PA production trust list.
- Veridex builds on Adobe's open-source TrustMark variant P watermark; the recovery concept and the
  canonical SBR API are also Adobe's prior art. Veridex's contribution is the open, self-hostable
  server, the Backblaze B2 recovery repository, the WORM transparency log, and the MCP surface, not
  the watermark or the SBR idea.
- PDQ is an internal recovery index, not a C2PA-registered fingerprint algorithm, so it is never
  advertised on `/services/supportedAlgorithms`.
- A single Veridex instance only recovers manifests it has ingested. The SBR spec's larger goal is
  federated, cross-repository lookup; a single instance does not deliver that network effect.
- The B2 Event-Notification ingest is wired and tested. Native event delivery is pending Backblaze's
  enterprise Event Notifications tier (1 TB stored plus a payment); the webhook, the B2 fetch, the
  ingest, and the recovery are downstream-verified, so once the rule is enabled, dropping an asset in
  B2 makes it auto-recoverable.

## License

Apache-2.0. See [LICENSE](./LICENSE).
