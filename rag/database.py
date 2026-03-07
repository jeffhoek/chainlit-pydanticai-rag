import asyncpg
from pgvector.asyncpg import register_vector

from config import settings

_pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kev_vulnerabilities (
    id SERIAL PRIMARY KEY,
    cve_id VARCHAR(20) UNIQUE NOT NULL,
    vendor_project TEXT,
    product TEXT,
    vulnerability_name TEXT,
    short_description TEXT,
    required_action TEXT,
    notes TEXT,
    date_added DATE,
    due_date DATE,
    known_ransomware_campaign_use VARCHAR(20),
    cwes TEXT[],
    content TEXT NOT NULL,
    embedding vector(1536)
);

CREATE INDEX IF NOT EXISTS kev_embedding_idx
    ON kev_vulnerabilities
    USING hnsw (embedding vector_cosine_ops);
"""


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def init_db() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool

    _pool = await asyncpg.create_pool(
        dsn=settings.get_database_dsn(),
        min_size=2,
        max_size=10,
        init=_init_connection,
    )

    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)

    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
