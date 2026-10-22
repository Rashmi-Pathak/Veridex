"""PostgresTransparencyStore: a durable, ordered record of the Merkle leaves.

Implements veridex_provenance.merkle.LeafStore. The transparency tree is in-memory and rebuilt by
replaying these leaves in order on startup, so inclusion proofs survive a restart or a second
instance instead of resetting to an empty tree while manifests persist in Postgres. Connections come
from a pooled, self-healing ConnectionPool, the same posture as PostgresIndex.
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool

_SCHEMA = """
CREATE TABLE IF NOT EXISTS merkle_leaves (
    seq bigserial PRIMARY KEY,
    manifest_id text NOT NULL,
    leaf_hash text NOT NULL
);
"""


class PostgresTransparencyStore:
    """Postgres-backed LeafStore. The bigserial seq preserves append order for replay."""

    def __init__(self, conninfo: str, *, min_size: int = 1, max_size: int = 4) -> None:
        self._pool = ConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            open=True,
            check=ConnectionPool.check_connection,
        )
        self.create_schema()

    def create_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(_SCHEMA)

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE merkle_leaves")

    def close(self) -> None:
        self._pool.close()

    def append(self, manifest_id: str, leaf_hash: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO merkle_leaves (manifest_id, leaf_hash) VALUES (%s, %s)",
                (manifest_id, leaf_hash),
            )

    def all(self) -> list[tuple[str, str]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT manifest_id, leaf_hash FROM merkle_leaves ORDER BY seq ASC")
            return [(str(m), str(h)) for m, h in cur.fetchall()]
