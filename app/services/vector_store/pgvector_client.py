"""PostgreSQL + pgvector implementation using raw SQL for tenant isolation."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.vector_store.base import (
    ChunkRecord,
    VectorSearchResult,
    VectorStore,
)

logger = get_logger(__name__)


def _vector_to_sql_literal(vec: list[float]) -> str:
    """Format Python list of floats as a pgvector string '[x1,x2,...]'."""
    return f"[{','.join(str(x) for x in vec)}]"


class PgVectorClient(VectorStore):
    """pgvector client using raw SQL to avoid asyncpg type-registration pitfalls."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_chunks(
        self,
        tenant_id: uuid.UUID,
        chunks: list[ChunkRecord],
    ) -> None:
        """Insert chunks using CAST(:embedding AS vector) and CAST(:meta AS jsonb)."""
        if not chunks:
            return

        # Ensure all chunks belong to the authenticated tenant
        for chunk in chunks:
            if chunk.tenant_id != tenant_id:
                raise ValueError(
                    f"Cross-tenant chunk insertion rejected: expected {tenant_id}, "
                    f"got {chunk.tenant_id}"
                )

        stmt = text(
            """
            INSERT INTO chunks (
                id, tenant_id, document_id, content, embedding, meta, chunk_index, created_at
            )
            VALUES (
                :id,
                :tenant_id,
                :document_id,
                :content,
                CAST(:embedding AS vector),
                CAST(:meta AS jsonb),
                :chunk_index,
                NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                meta = EXCLUDED.meta,
                chunk_index = EXCLUDED.chunk_index;
            """
        )

        for chunk in chunks:
            params: dict[str, Any] = {
                "id": chunk.id,
                "tenant_id": chunk.tenant_id,
                "document_id": chunk.document_id,
                "content": chunk.content,
                "embedding": _vector_to_sql_literal(chunk.embedding),
                "meta": json.dumps(chunk.meta),
                "chunk_index": chunk.chunk_index,
            }
            await self.session.execute(stmt, params)

        await self.session.flush()

    async def search(
        self,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        """Query nearest chunks strictly filtered by tenant_id."""
        vector_str = _vector_to_sql_literal(query_vector)

        # 1 - (embedding <=> query) gives cosine similarity (1 = identical, -1 = opposite)
        stmt = text(
            """
            SELECT
                id,
                tenant_id,
                document_id,
                content,
                meta,
                chunk_index,
                1 - (embedding <=> CAST(:query_vector AS vector)) AS score
            FROM chunks
            WHERE tenant_id = :tenant_id
            ORDER BY embedding <=> CAST(:query_vector AS vector) ASC
            LIMIT :top_k;
            """
        )

        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "query_vector": vector_str,
            "top_k": top_k,
        }

        result = await self.session.execute(stmt, params)
        rows = result.fetchall()

        results: list[VectorSearchResult] = []
        for row in rows:
            raw_meta = row[4]
            parsed_meta: dict[str, Any] = {}
            if isinstance(raw_meta, str):
                try:
                    loaded = json.loads(raw_meta)
                    if isinstance(loaded, dict):
                        parsed_meta = loaded
                except json.JSONDecodeError:
                    parsed_meta = {}
            elif isinstance(raw_meta, dict):
                parsed_meta = raw_meta

            results.append(
                VectorSearchResult(
                    chunk_id=uuid.UUID(str(row[0])),
                    tenant_id=uuid.UUID(str(row[1])),
                    document_id=uuid.UUID(str(row[2])),
                    content=str(row[3]),
                    meta=parsed_meta,
                    chunk_index=int(row[5]),
                    score=float(row[6]),
                )
            )

        return results

    async def delete_by_document(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> None:
        """Delete all chunks belonging to a document under the specified tenant."""
        stmt = text(
            """
            DELETE FROM chunks
            WHERE tenant_id = :tenant_id AND document_id = :document_id;
            """
        )
        await self.session.execute(
            stmt,
            {"tenant_id": tenant_id, "document_id": document_id},
        )
        await self.session.flush()
