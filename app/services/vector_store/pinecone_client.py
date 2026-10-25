"""Pinecone vector store implementation stub for multi-backend architecture."""

from __future__ import annotations

import uuid

from app.core.config import settings
from app.services.vector_store.base import (
    ChunkRecord,
    VectorSearchResult,
    VectorStore,
)


class PineconeClient(VectorStore):
    """Pinecone vector store adapter with tenant namespacing."""

    def __init__(self) -> None:
        if not settings.PINECONE_API_KEY or not settings.PINECONE_INDEX_NAME:
            raise NotImplementedError(
                "Pinecone backend not configured. Set PINECONE_API_KEY and "
                "PINECONE_INDEX_NAME in environment."
            )

    async def upsert_chunks(
        self,
        tenant_id: uuid.UUID,
        chunks: list[ChunkRecord],
    ) -> None:
        raise NotImplementedError("Pinecone upsert not configured.")

    async def search(
        self,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        raise NotImplementedError("Pinecone search not configured.")

    async def delete_by_document(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> None:
        raise NotImplementedError("Pinecone delete not configured.")
