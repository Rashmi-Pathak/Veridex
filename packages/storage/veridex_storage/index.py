"""PostgresIndex: the recovery Index, backed by Postgres.

Implements the Index protocol (see veridex_provenance.resolver.Index) on Postgres:

- manifests as jsonb keyed by manifest id,
- watermark bindings as an exact-match primary-key lookup (a B-tree),
- PDQ perceptual hashes as native bit(256).

Nearest-fingerprint search has two wired paths, chosen at startup by the database's capability: with
pgvector 0.7+ it uses the `<~>` Hamming operator accelerated by an HNSW bit_hamming_ops index (the
production path on the live Postgres deploy); without pgvector, or pre-0.7, it falls back to the
exact Postgres bit_count of the XOR (`#`), which needs no extension. Both return the same nearest
(manifest_id, distance) for the curated recovery set; the path is selected automatically.

Connections come from a psycopg_pool.ConnectionPool with a liveness check on checkout, so a dropped
connection (a Postgres restart or idle timeout over a multi-day window) self-heals instead of
wedging recovery. register() runs the three index writes in one transaction, so a partial ingest
rolls back rather than orphaning an unrecoverable manifest. The API layer offloads these blocking
calls off the event loop. The remaining synchronous-vs-async driver swap is the only deferred item.
"""

from __future__ import annotations

import json

from psycopg_pool import ConnectionPool

from veridex_provenance.models import Manifest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS manifests (
    manifest_id text PRIMARY KEY,
    body jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS watermark_bindings (
    watermark_id text PRIMARY KEY,
    manifest_id text NOT NULL
);
CREATE TABLE IF NOT EXISTS perceptual_hashes (
    id bigserial PRIMARY KEY,
    manifest_id text NOT NULL,
    pdq bit(256) NOT NULL
);
CREATE INDEX IF NOT EXISTS perceptual_hashes_manifest_idx ON perceptual_hashes (manifest_id);
"""

_INSERT_MANIFEST = (
    "INSERT INTO manifests (manifest_id, body) VALUES (%s, %s) "
    "ON CONFLICT (manifest_id) DO UPDATE SET body = EXCLUDED.body"
)
# A watermark binding is immutable: DO NOTHING (not DO UPDATE) so a second ingest can never
# re-point an existing watermark id to a different manifest and poison recovery. The API layer
# rejects a re-point with a 409 before it reaches here; this is the defense-in-depth at the store.
_INSERT_BINDING = (
    "INSERT INTO watermark_bindings (watermark_id, manifest_id) VALUES (%s, %s) "
    "ON CONFLICT (watermark_id) DO NOTHING"
)
_INSERT_FINGERPRINT = "INSERT INTO perceptual_hashes (manifest_id, pdq) VALUES (%s, %s::bit(256))"


class PostgresIndex:
    """Postgres-backed Index. Construct with a libpq conninfo string or URL."""

    def __init__(self, conninfo: str, *, min_size: int = 1, max_size: int = 8) -> None:
        self._pool = ConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            open=True,
            check=ConnectionPool.check_connection,
        )
        # True once create_schema() confirms pgvector >= 0.7 (the bit_hamming_ops `<~>` operator and
        # HNSW opclass); until then nearest_fingerprint uses the exact bit_count scan.
        self._hnsw = False

    def create_schema(self) -> None:
        """Idempotently create the tables and indexes. Safe to call on every startup. Where pgvector
        0.7+ is present, also create an HNSW bit_hamming_ops index on the PDQ column and route
        nearest-fingerprint search through the `<~>` Hamming operator; otherwise keep the exact
        bit_count scan, so a Postgres without pgvector (or pre-0.7) still works unchanged."""
        with self._pool.connection() as conn:
            conn.execute(_SCHEMA)
        self._hnsw = self._try_enable_hnsw()

    def _try_enable_hnsw(self) -> bool:
        """Enable the pgvector HNSW Hamming path when available. Each step runs in its own
        transaction so a failure (no privilege to CREATE EXTENSION, or pgvector < 0.7 lacking the
        bit_hamming_ops opclass) leaves the schema intact and the bit_count fallback in place."""
        try:
            with self._pool.connection() as conn:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:  # noqa: BLE001 - no pgvector / no privilege -> keep the bit_count fallback
            return False
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_opclass WHERE opcname = 'bit_hamming_ops'")
            if cur.fetchone() is None:
                return False  # pgvector present but < 0.7 (no bit-vector Hamming ops)
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS perceptual_hashes_pdq_hnsw "
                    "ON perceptual_hashes USING hnsw (pdq bit_hamming_ops)"
                )
        except Exception:  # noqa: BLE001 - index build refused -> keep the exact bit_count path
            return False
        return True

    def clear(self) -> None:
        """Truncate all index tables (used by tests for isolation)."""
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE manifests, watermark_bindings, perceptual_hashes")

    def close(self) -> None:
        self._pool.close()

    def put_manifest(self, manifest: Manifest) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                _INSERT_MANIFEST, (manifest.manifest_id, json.dumps(manifest.model_dump()))
            )

    def get_manifest(self, manifest_id: str) -> Manifest | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT body FROM manifests WHERE manifest_id = %s", (manifest_id,))
            row = cur.fetchone()
        return Manifest.model_validate(row[0]) if row is not None else None

    def put_watermark_binding(self, watermark_id: str, manifest_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(_INSERT_BINDING, (watermark_id, manifest_id))

    def manifest_for_watermark(self, watermark_id: str) -> str | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT manifest_id FROM watermark_bindings WHERE watermark_id = %s",
                (watermark_id,),
            )
            row = cur.fetchone()
        return str(row[0]) if row is not None else None

    def put_fingerprint(self, pdq_bits: str, manifest_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(_INSERT_FINGERPRINT, (manifest_id, pdq_bits))

    def register(self, manifest: Manifest, watermark_id: str, pdq_bits: str) -> None:
        # All three writes in one transaction: a failure (e.g. a bad pdq cast) rolls the whole
        # ingest back, so a manifest is never stored without its recovery pointers.
        with self._pool.connection() as conn:
            conn.execute(
                _INSERT_MANIFEST, (manifest.manifest_id, json.dumps(manifest.model_dump()))
            )
            conn.execute(_INSERT_BINDING, (watermark_id, manifest.manifest_id))
            conn.execute(_INSERT_FINGERPRINT, (manifest.manifest_id, pdq_bits))

    def nearest_fingerprint(self, pdq_bits: str, threshold: int) -> tuple[str, int] | None:
        # Hamming distance = set bits of the XOR. With pgvector 0.7+ this runs through the `<~>`
        # operator (accelerated by the HNSW bit_hamming_ops index); otherwise it is the exact
        # bit_count scan. Both return the same nearest (manifest_id, distance); the threshold bounds
        # a false match.
        with self._pool.connection() as conn, conn.cursor() as cur:
            if self._hnsw:
                cur.execute(
                    "SELECT manifest_id, (pdq <~> %s::bit(256))::int AS dist "
                    "FROM perceptual_hashes ORDER BY pdq <~> %s::bit(256) ASC LIMIT 1",
                    (pdq_bits, pdq_bits),
                )
            else:
                cur.execute(
                    "SELECT manifest_id, bit_count(pdq # %s::bit(256))::int AS dist "
                    "FROM perceptual_hashes ORDER BY dist ASC LIMIT 1",
                    (pdq_bits,),
                )
            row = cur.fetchone()
        if row is None or row[1] > threshold:
            return None
        return (str(row[0]), int(row[1]))

    def fingerprints_for(self, manifest_id: str) -> list[str]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT pdq FROM perceptual_hashes WHERE manifest_id = %s", (manifest_id,))
            return [str(r[0]) for r in cur.fetchall()]

    def kind(self) -> str:
        return "postgres+hnsw" if self._hnsw else "postgres+bitcount"
