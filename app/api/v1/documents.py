"""Document management API endpoints with multi-tenant isolation and robust error handling."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_vector_store, rate_limited_tenant
from app.core.exceptions import (
    CorruptedPDFError,
    DuplicateDocumentError,
    EmbeddingServiceError,
    EmbeddingTimeoutError,
    EmptyDocumentError,
)
from app.db.models.document import Document
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.schemas.document import (
    DocumentItem,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.services.rag.ingestion import ingest_document
from app.services.vector_store.base import VectorStore

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a PDF document",
)
async def upload_document(
    file: UploadFile = File(..., description="PDF document to ingest"),
    tenant: Tenant = Depends(rate_limited_tenant),
    db: AsyncSession = Depends(get_db),
    vector_store: VectorStore = Depends(get_vector_store),
) -> DocumentUploadResponse:
    """Ingest a PDF file into the authenticated tenant's isolated vector knowledge base.

    Strictly enforces:
    - PDF extension verification.
    - Tenant-scoped deduplication (HTTP 409).
    - Corrupted or unreadable PDF detection (HTTP 422).
    - Embedding provider timeouts (HTTP 504) and provider failures (HTTP 502).
    - Tenant isolation on all database and vector store operations.
    """
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF documents are supported (.pdf).",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    try:
        doc = await ingest_document(
            tenant_id=tenant.id,
            filename=filename,
            file_bytes=file_bytes,
            db=db,
            vector_store=vector_store,
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate document: {exc}",
        ) from exc
    except (CorruptedPDFError, EmptyDocumentError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid document: {exc}",
        ) from exc
    except EmbeddingTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Embedding provider timed out: {exc}",
        ) from exc
    except EmbeddingServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Embedding provider error: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return DocumentUploadResponse(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        message="Document uploaded, chunked, embedded, and indexed successfully.",
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List tenant's uploaded documents",
)
async def list_documents(
    tenant: Tenant = Depends(rate_limited_tenant),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """Retrieve all documents owned strictly by the authenticated tenant."""
    stmt = (
        select(Document)
        .where(Document.tenant_id == tenant.id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    documents = result.scalars().all()

    items = [DocumentItem.model_validate(doc) for doc in documents]
    return DocumentListResponse(documents=items, total=len(items))
