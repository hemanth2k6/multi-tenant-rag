"""RAG query endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import rate_limited_tenant
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.schemas.query import QueryRequest, QueryResponse, SourceChunk
from app.services.rag.retriever import retrieve_and_answer
from app.services.vector_store.pgvector_client import PgVectorClient

router = APIRouter(prefix="/query", tags=["query"])


@router.post(
    "",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Query tenant knowledge base using RAG",
)
async def query_knowledge_base(
    request: QueryRequest,
    tenant: Tenant = Depends(rate_limited_tenant),
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """Execute semantic vector search against tenant documents and synthesize an answer."""
    vector_store = PgVectorClient(db)

    answer, sources = await retrieve_and_answer(
        tenant_id=tenant.id,
        question=request.question,
        top_k=request.top_k,
        vector_store=vector_store,
    )

    source_chunks = [
        SourceChunk(
            chunk_id=src.chunk_id,
            document_id=src.document_id,
            content=src.content,
            score=src.score,
            meta=src.meta,
        )
        for src in sources
    ]

    return QueryResponse(
        answer=answer,
        sources=source_chunks,
        question=request.question,
    )
