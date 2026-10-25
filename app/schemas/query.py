"""Query request and response schemas."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Schema for querying the tenant's knowledge base."""

    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class SourceChunk(BaseModel):
    """Schema for individual retrieved source chunk."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float
    meta: dict[str, Any]


class QueryResponse(BaseModel):
    """Schema returned after RAG answer generation."""

    answer: str
    sources: list[SourceChunk]
    question: str
