"""Vector store abstraction and common types."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ChunkRecord:
    """Represents a text chunk prepared for vector storage."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    embedding: list[float]
    meta: dict[str, Any]
    chunk_index: int


@dataclass
class VectorSearchResult:
    """Represents a retrieved chunk with similarity score and tenant context."""

    chunk_id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float
    meta: dict[str, Any]
    chunk_index: int


class VectorStore(ABC):
    """Abstract vector store contract supporting multi-tenant isolation."""

    @abstractmethod
    async def upsert_chunks(
        self,
        tenant_id: uuid.UUID,
        chunks: list[ChunkRecord],
    ) -> None:
        """Insert or update chunks scoped to the given tenant."""

    @abstractmethod
    async def search(
        self,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        """Perform cosine similarity search strictly scoped by tenant_id."""

    @abstractmethod
    async def delete_by_document(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> None:
        """Delete all chunks for a document scoped to the given tenant."""
