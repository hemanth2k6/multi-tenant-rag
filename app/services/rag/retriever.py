"""RAG retriever service with cross-tenant defence-in-depth filtering."""

from __future__ import annotations

import uuid

from app.core.logging import get_logger
from app.services.rag.embedder import embed_chunks, generate_answer
from app.services.vector_store.base import VectorSearchResult, VectorStore

logger = get_logger(__name__)


async def retrieve_and_answer(
    tenant_id: uuid.UUID,
    question: str,
    top_k: int,
    vector_store: VectorStore,
) -> tuple[str, list[VectorSearchResult]]:
    """Execute the query pipeline: embedding, vector search, defence-in-depth, generation.

    Args:
        tenant_id: Authenticated tenant ID.
        question: User query string.
        top_k: Number of chunks to retrieve.
        vector_store: Vector store adapter.

    Returns:
        tuple of (synthesized_answer, filtered_sources)
    """
    # 1. Embed query vector with task_type='retrieval_query'
    query_embeddings = await embed_chunks([question], task_type="retrieval_query")
    if not query_embeddings:
        raise RuntimeError("Failed to compute embedding vector for query")

    query_vector = query_embeddings[0]

    # 2. Vector search strictly scoped by tenant_id in SQL
    raw_results = await vector_store.search(
        tenant_id=tenant_id,
        query_vector=query_vector,
        top_k=top_k,
    )

    # 3. DEFENCE-IN-DEPTH CHECK: Validate tenant_id on every returned record in Python
    isolated_results: list[VectorSearchResult] = []
    for result in raw_results:
        if result.tenant_id != tenant_id:
            logger.critical(
                "SECURITY ALERT: Cross-tenant vector leakage detected and dropped!",
                extra={
                    "authenticated_tenant": str(tenant_id),
                    "breaching_chunk_tenant": str(result.tenant_id),
                    "chunk_id": str(result.chunk_id),
                },
            )
            continue
        isolated_results.append(result)

    if not isolated_results:
        logger.info(
            "No matching chunks found for query",
            extra={"tenant_id": str(tenant_id), "top_k": top_k},
        )
        return (
            "I cannot answer this based on the provided documents.",
            [],
        )

    # 4. Generate answer using Gemini chat model with retrieved context
    contexts = [res.content for res in isolated_results]
    answer = await generate_answer(question=question, contexts=contexts)

    return answer, isolated_results
