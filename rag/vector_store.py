import asyncpg
import numpy as np


class PgVectorStore:
    """PostgreSQL pgvector-backed vector store with cosine similarity search."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def search(self, query_embedding: list[float], top_k: int = 5) -> list[str]:
        """Find top-k most similar documents using cosine distance."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT content
                FROM kev_vulnerabilities
                ORDER BY embedding <=> $1
                LIMIT $2
                """,
                np.array(query_embedding, dtype=np.float32),
                top_k,
            )
        return [row["content"] for row in rows]

    async def get_document_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT count(*) FROM kev_vulnerabilities")
