"""Document management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import rate_limited_tenant
from app.db.models.document import Document
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.schemas.document import (
    DocumentItem,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.services.rag.ingestion import DuplicateDocumentError, ingest_document
from app.services.vector_store.pgvector_client import PgVectorClient

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
) -> DocumentUploadResponse:
    """Ingest a PDF file into the tenant's isolated vector knowledge base."""
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

    vector_store = PgVectorClient(db)

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
    """Retrieve all documents owned by the authenticated tenant."""
    stmt = (
        select(Document).where(Document.tenant_id == tenant.id).order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    documents = result.scalars().all()

    items = [DocumentItem.model_validate(doc) for doc in documents]
    return DocumentListResponse(documents=items, total=len(items))
