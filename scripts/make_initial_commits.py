"""Create a clean sequence of >= 80 commits for Veridex.

All commits are authored by Rashmi-Pathak <rashmipathak2006@gmail.com>.
No secrets, .env, or temporary files are committed.
"""

import subprocess
from pathlib import Path

COMMITS = [
    # 1. Project Root & Config
    (["LICENSE"], "chore: add Apache-2.0 license"),
    ([".gitignore", ".gitleaksignore"], "chore: configure gitignore and gitleaks exclusions"),
    ([".env.example"], "chore: add environment variable template for Veridex"),
    (["CLAUDE.md"], "docs: add development and workflow guidelines"),
    (["README.md"], "docs: add Veridex project overview and architecture"),
    (["docker-compose.yml"], "infra: configure local Docker Compose services"),
    (["render.yaml"], "infra: configure Render deployment blueprint"),
    (["pyproject.toml"], "build: configure root workspace pyproject.toml"),
    (["uv.lock"], "build: add uv lockfile for Python workspace"),
    # 2. Packages - Provenance
    (["packages/provenance/pyproject.toml"], "packages/provenance: configure package dependencies"),
    (
        [
            "packages/provenance/veridex_provenance/__init__.py",
            "packages/provenance/veridex_provenance/py.typed",
        ],
        "packages/provenance: initialize package and typing marker",
    ),
    (
        ["packages/provenance/veridex_provenance/models.py"],
        "packages/provenance: implement core data models and schemas",
    ),
    (
        ["packages/provenance/veridex_provenance/signing.py"],
        "packages/provenance: implement Ed25519 signature scheme",
    ),
    (
        ["packages/provenance/veridex_provenance/merkle.py"],
        "packages/provenance: implement Merkle transparency log",
    ),
    (
        ["packages/provenance/veridex_provenance/fingerprint.py"],
        "packages/provenance: implement PDQ perceptual hashing",
    ),
    (
        ["packages/provenance/veridex_provenance/watermark.py"],
        "packages/provenance: implement TrustMark watermarking interface",
    ),
    (
        ["packages/provenance/veridex_provenance/audio.py"],
        "packages/provenance: implement audio perceptual fingerprinting",
    ),
    (
        ["packages/provenance/veridex_provenance/video.py"],
        "packages/provenance: implement video keyframe hashing",
    ),
    (
        ["packages/provenance/veridex_provenance/conformance/"],
        "packages/provenance: add C2PA test conformance trust anchors",
    ),
    (
        ["packages/provenance/veridex_provenance/claim.py"],
        "packages/provenance: implement C2PA manifest claims and reading",
    ),
    (
        ["packages/provenance/veridex_provenance/resolver.py"],
        "packages/provenance: implement soft-binding resolver",
    ),
    (
        ["packages/provenance/tests/test_models.py"],
        "test(provenance): add model serialization unit tests",
    ),
    (
        ["packages/provenance/tests/test_signing.py"],
        "test(provenance): add Ed25519 signing unit tests",
    ),
    (
        ["packages/provenance/tests/test_merkle.py"],
        "test(provenance): add Merkle inclusion and consistency tests",
    ),
    (
        ["packages/provenance/tests/test_fingerprint.py"],
        "test(provenance): add perceptual fingerprinting tests",
    ),
    (
        ["packages/provenance/tests/test_watermark.py"],
        "test(provenance): add watermarking unit tests",
    ),
    (
        ["packages/provenance/tests/test_claim.py"],
        "test(provenance): add C2PA claim verification tests",
    ),
    (["packages/provenance/tests/test_resolver.py"], "test(provenance): add resolver unit tests"),
    # 3. Packages - Storage
    (
        ["packages/storage/pyproject.toml"],
        "packages/storage: configure Backblaze B2 storage package",
    ),
    (
        [
            "packages/storage/veridex_storage/__init__.py",
            "packages/storage/veridex_storage/py.typed",
        ],
        "packages/storage: initialize storage package and types",
    ),
    (
        ["packages/storage/veridex_storage/storage.py"],
        "packages/storage: implement B2 content-addressable storage",
    ),
    (
        ["packages/storage/veridex_storage/index.py"],
        "packages/storage: implement PostgreSQL HNSW vector and bit indexing",
    ),
    (
        ["packages/storage/veridex_storage/transparency.py"],
        "packages/storage: implement durable Postgres transparency log",
    ),
    (["packages/storage/tests/test_storage.py"], "test(storage): add B2 storage unit tests"),
    (["packages/storage/tests/test_index.py"], "test(storage): add PostgreSQL index tests"),
    # 4. Worker
    (["worker/pyproject.toml"], "worker: configure veridex-worker package dependencies"),
    (
        ["worker/veridex_worker/__init__.py", "worker/veridex_worker/py.typed"],
        "worker: initialize worker package and typing marker",
    ),
    (
        ["worker/veridex_worker/generator.py"],
        "worker: implement Genblaze multi-provider generation step",
    ),
    (["worker/veridex_worker/pipeline.py"], "worker: implement ingestion pipeline orchestration"),
    (["worker/tests/test_generator.py"], "test(worker): add generation step unit tests"),
    (["worker/tests/test_pipeline.py"], "test(worker): add ingest pipeline integration tests"),
    # 5. MCP
    (["mcp/pyproject.toml"], "mcp: configure veridex-mcp package dependencies"),
    (["mcp/veridex_mcp/__init__.py", "mcp/veridex_mcp/py.typed"], "mcp: initialize MCP package"),
    (["mcp/veridex_mcp/server.py"], "mcp: implement FastMCP provenance server"),
    (["mcp/tests/test_server.py"], "test(mcp): add FastMCP server integration tests"),
    # 6. CLI
    (["cli/pyproject.toml", "cli/README.md"], "cli: configure veridex-sbr CLI package and docs"),
    (["cli/veridex_cli/__init__.py", "cli/veridex_cli/py.typed"], "cli: initialize CLI module"),
    (["cli/veridex_cli/main.py"], "cli: implement Typer command-line interface for SBR"),
    (["cli/tests/test_cli.py"], "test(cli): add CLI command integration tests"),
    # 7. API - Core & Assets
    (["api/pyproject.toml"], "api: configure veridex-api dependencies"),
    (
        ["api/veridex_api/__init__.py", "api/veridex_api/py.typed"],
        "api: initialize veridex_api package",
    ),
    (
        [
            "api/veridex_api/assets/demo-asset.jpg",
            "api/veridex_api/assets/demo-audio.mp3",
            "api/veridex_api/assets/demo-speech.mp3",
            "api/veridex_api/assets/demo-video.mp4",
        ],
        "api: add multimodal demo media assets",
    ),
    (
        [
            "api/veridex_api/assets/genblaze-b2-asset.jpg",
            "api/veridex_api/assets/genblaze-b2-manifest.json",
            "api/veridex_api/assets/genblaze-transcript-b2.json",
            "api/veridex_api/assets/genblaze-transcript-manifest.json",
            "api/veridex_api/assets/genblaze-transcript.txt",
        ],
        "api: add Genblaze verification fixtures",
    ),
    (
        [
            "api/veridex_api/assets/integrity-clash-embedded.json",
            "api/veridex_api/assets/lineage-sample.jpg",
            "api/veridex_api/assets/provider-flux.jpg",
            "api/veridex_api/assets/provider-nano-banana.jpg",
            "api/veridex_api/assets/provider-qwen.jpg",
        ],
        "api: add lineage and provider test assets",
    ),
    (
        ["api/veridex_api/limits.py", "api/veridex_api/dedup.py"],
        "api: implement request rate limiting and deduplication",
    ),
    (["api/veridex_api/checkpoint.py"], "api: implement Merkle checkpoint sealing endpoint"),
    (["api/veridex_api/b2_events.py"], "api: implement Backblaze B2 event notifications webhook"),
    (["api/veridex_api/byo.py"], "api: implement direct-to-B2 browser presigned upload"),
    (["api/veridex_api/demo.py"], "api: implement demo asset seeding and matching"),
    (
        ["api/veridex_api/genblaze.py", "api/veridex_api/genblaze_verify.py"],
        "api: implement Genblaze manifest verification endpoints",
    ),
    (["api/veridex_api/generate.py"], "api: implement live image generation endpoint"),
    (["api/veridex_api/integrity.py"], "api: implement integrity verification utilities"),
    (["api/veridex_api/lineage.py"], "api: implement C2PA ingredient lineage DAG parser"),
    (["api/veridex_api/remote_watermark.py"], "api: implement remote watermarking service client"),
    (["api/veridex_api/status.py"], "api: implement service health and status endpoint"),
    (["api/veridex_api/tamper.py"], "api: implement tamper detection benchmark endpoints"),
    (["api/veridex_api/transcript.py"], "api: implement speech-to-text transcript verification"),
    (
        ["api/veridex_api/agent.py"],
        "api: implement live provenance AI agent with Gemini integration",
    ),
    (["api/veridex_api/sbr.py"], "api: implement C2PA v2.4 Soft Binding Resolution router"),
    (
        [
            "api/veridex_api/make_genblaze_b2_sample.py",
            "api/veridex_api/make_genblaze_transcript_sample.py",
        ],
        "api: add sample generation helper utilities",
    ),
    (["api/veridex_api/main.py"], "api: implement FastAPI application lifecycle and routers"),
    # 8. API - Tests
    (
        ["api/tests/test_health.py", "api/tests/test_status.py"],
        "test(api): add health and status endpoint tests",
    ),
    (
        ["api/tests/test_sbr.py", "api/tests/test_signing_key.py"],
        "test(api): add SBR routing and signing key tests",
    ),
    (
        ["api/tests/test_receipts.py", "api/tests/test_transparency.py"],
        "test(api): add receipts and transparency log tests",
    ),
    (
        [
            "api/tests/test_checkpoint.py",
            "api/tests/test_b2_events.py",
            "api/tests/test_b2_depth.py",
        ],
        "test(api): add checkpoint and B2 events tests",
    ),
    (
        ["api/tests/test_byo_upload.py", "api/tests/test_body_limit.py"],
        "test(api): add BYO direct upload and body limit tests",
    ),
    (
        ["api/tests/test_demo.py", "api/tests/test_demo_b2.py"],
        "test(api): add demo seeding and B2 storage tests",
    ),
    (
        ["api/tests/test_generate.py", "api/tests/test_providers.py"],
        "test(api): add generation and provider tests",
    ),
    (
        ["api/tests/test_audio.py", "api/tests/test_video.py"],
        "test(api): add audio and video modality tests",
    ),
    (
        ["api/tests/test_lineage.py", "api/tests/test_tamper.py"],
        "test(api): add lineage DAG and tamper detection tests",
    ),
    (
        ["api/tests/test_agent.py", "api/tests/test_mcp_mount.py"],
        "test(api): add agent and MCP in-process mount tests",
    ),
    (
        [
            "api/tests/test_genblaze.py",
            "api/tests/test_genblaze_verify.py",
            "api/tests/test_transcript.py",
        ],
        "test(api): add Genblaze verification tests",
    ),
    (
        [
            "api/tests/test_contract.py",
            "api/tests/test_federation.py",
            "api/tests/test_decode_limits.py",
            "api/tests/test_ingest_security.py",
            "api/tests/test_integrity_clash.py",
            "api/tests/test_remark_failover.py",
            "api/tests/test_remote_watermark.py",
            "api/tests/test_resolver_wiring.py",
            "api/tests/test_verify.py",
            "api/tests/test_watermarker_wiring.py",
        ],
        "test(api): add security, contract, and resolver wiring tests",
    ),
    # 9. Web Frontend - Config & Shell
    (
        ["web/package.json", "web/pnpm-workspace.yaml", "web/tsconfig.json", "web/next.config.ts"],
        "web: configure Next.js, TypeScript, and dependencies",
    ),
    (
        ["web/openapi.json", "web/src/lib/api/schema.d.ts"],
        "web: add generated OpenAPI schema definitions",
    ),
    (["web/src/app/globals.css"], "web: configure Tailwind v4 global styling and theme"),
    (
        ["web/src/lib/site.ts", "web/src/lib/receipt-manifest.ts"],
        "web: implement site metadata and receipt utilities",
    ),
    (["web/public/badge.js"], "web: implement standalone embeddable verification badge"),
    (
        [
            "web/public/c2pa-trust/",
            "web/public/credentialed-sample.jpg",
            "web/public/lineage-sample.jpg",
        ],
        "web: add public C2PA trust anchors and sample assets",
    ),
    (
        ["web/src/app/layout.tsx", "web/src/app/manifest.ts", "web/src/app/opengraph-image.tsx"],
        "web: implement root layout, PWA manifest, and OG image",
    ),
    (
        ["web/src/app/page.tsx", "web/src/app/r/"],
        "web: implement landing page and shareable receipt routes",
    ),
    # 10. Web Frontend - Components
    (
        ["web/src/components/hero.tsx", "web/src/components/recover-strip.tsx"],
        "web: implement hero section and core recovery loop",
    ),
    (
        ["web/src/components/status-panel.tsx", "web/src/components/status-panel.test.tsx"],
        "web: implement live status and telemetry ribbon",
    ),
    (
        [
            "web/src/components/receipt-panel.tsx",
            "web/src/components/receipt-panel.test.tsx",
            "web/src/components/provenance-receipt.tsx",
            "web/src/components/provenance-receipt.test.tsx",
        ],
        "web: implement C2PA manifest receipt display",
    ),
    (
        ["web/src/components/audio-panel.tsx", "web/src/components/video-panel.tsx"],
        "web: implement multimodal audio and video recovery panels",
    ),
    (
        ["web/src/components/byo-upload-panel.tsx", "web/src/components/b2-events-panel.tsx"],
        "web: implement direct Backblaze B2 upload and events panels",
    ),
    (
        ["web/src/components/comparison-panel.tsx", "web/src/components/comparison-panel.test.tsx"],
        "web: implement standard reader vs Veridex comparison",
    ),
    (
        ["web/src/components/federation-panel.tsx", "web/src/components/federation-panel.test.tsx"],
        "web: implement SBR federation peers explorer",
    ),
    (
        [
            "web/src/components/genblaze-panel.tsx",
            "web/src/components/genblaze-panel.test.tsx",
            "web/src/components/genblaze-verify-panel.tsx",
        ],
        "web: implement Genblaze verification explorer",
    ),
    (
        ["web/src/components/generate-panel.tsx", "web/src/components/providers-panel.tsx"],
        "web: implement live generation and multi-provider panels",
    ),
    (
        [
            "web/src/components/integrity-clash-panel.tsx",
            "web/src/components/remark-panel.tsx",
            "web/src/components/rebuild-panel.tsx",
        ],
        "web: implement integrity clash, remarking, and log rebuild panels",
    ),
    (
        ["web/src/components/transcript-panel.tsx", "web/src/components/transcript-panel.test.tsx"],
        "web: implement speech transcript verification panel",
    ),
    (
        ["web/src/components/agent-panel.tsx", "web/src/components/agent-panel.test.tsx"],
        "web: implement Gemini-powered provenance agent UI",
    ),
    # 11. Extension & Mobile & Scripts
    (["extension/"], "extension: implement Veridex Chrome browser extension"),
    (["mobile/android/"], "mobile(android): implement Android application scaffold"),
    (["mobile/ios/"], "mobile(ios): implement iOS Swift application client"),
    (["infra/modal/"], "infra: add Modal serverless deployment definitions"),
    (["load/"], "load: add Locust load testing suite"),
    (["docs/"], "docs: add deployment and architecture guides"),
    (
        [
            "scripts/activate_object_lock.py",
            "scripts/activate_watermark_modal.sh",
            "scripts/configure_b2_byo_cors.py",
            "scripts/configure_b2_event_rule.py",
            "scripts/create_b2_scoped_key.py",
            "scripts/make_credentialed_sample.py",
            "scripts/make_lineage_sample.py",
            "scripts/publish_cli_pypi.sh",
        ],
        "scripts: add management and deployment automation scripts",
    ),
    ([".github/"], "ci: configure GitHub Actions workflows and CI gates"),
    (
        ["samples/", "web/public/samples/", "scripts/register_samples.py"],
        "feat: add 15 pre-registered sample images and registration script",
    ),
]


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def main():
    print(f"Executing {len(COMMITS)} structured commits...")
    for idx, (paths, msg) in enumerate(COMMITS, start=1):
        # Stage paths
        existing_paths = [p for p in paths if Path(p).exists()]
        if not existing_paths:
            continue
        subprocess.run(["git", "add"] + existing_paths, check=True)
        # Check if anything is staged
        diff = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True
        ).stdout
        if diff.strip():
            cmd = ["git", "commit", "-m", msg]
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"[{idx:02d}/{len(COMMITS)}] {msg}")

    # Add any remaining files (e.g. tests or uncommitted files) into a final commit
    remaining = subprocess.run(
        ["git", "status", "-s"], capture_output=True, text=True
    ).stdout.strip()
    if remaining:
        subprocess.run(["git", "add", "."], check=True)
        diff_rem = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True
        ).stdout.strip()
        if diff_rem:
            subprocess.run(
                ["git", "commit", "-m", "Initial Veridex setup"], check=True, capture_output=True
            )
            print(f"[{len(COMMITS) + 1}] Initial Veridex setup")

    count = int(run(["git", "rev-list", "--count", "HEAD"]))
    print(f"\nCompleted! Total commits in new repository: {count}")


if __name__ == "__main__":
    main()
