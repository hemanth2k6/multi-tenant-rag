"""Document ingestion pipeline: dedup, extraction, chunking, embedding, storage."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.document import Document
from app.services.rag.chunker import chunk_extracted_pages
from app.services.rag.embedder import embed_chunks
from app.services.rag.extractor import extract_pdf_pages
from app.services.vector_store.base import ChunkRecord, VectorStore

logger = get_logger(__name__)


class DuplicateDocumentError(Exception):
    """Raised when a tenant uploads an identical document."""

    def __init__(self, filename: str, file_hash: str) -> None:
        super().__init__(
            f"Document '{filename}' with hash '{file_hash[:12]}...' already exists for this tenant."
        )
        self.filename = filename
        self.file_hash = file_hash


async def ingest_document(
    tenant_id: uuid.UUID,
    filename: str,
    file_bytes: bytes,
    db: AsyncSession,
    vector_store: VectorStore,
) -> Document:
    """Execute the end-to-end ingestion pipeline with strict tenant isolation.

    Pipeline Steps:
    1. Compute SHA-256 hash for tenant-scoped deduplication.
    2. Check for duplicate upload (HTTP 409).
    3. Persist Document entity with 'processing' status.
    4. Extract text pages via PyPDF2.
    5. Generate token-bounded chunks (512 max tokens, 128 overlap).
    6. Request 768-dim embeddings from Gemini (task_type='retrieval_document').
    7. Upsert chunks into vector store scoped to tenant_id.
    8. Update Document status to 'ready'.
    """
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Step 1 & 2: Deduplication check scoped to tenant
    stmt = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.file_hash == file_hash,
    )
    existing_doc = (await db.execute(stmt)).scalar_one_or_none()
    if existing_doc is not None:
        logger.info(
            "Duplicate upload rejected",
            extra={
                "tenant_id": str(tenant_id),
                "filename": filename,
                "file_hash": file_hash[:8],
            },
        )
        raise DuplicateDocumentError(filename=filename, file_hash=file_hash)

    # Step 3: Create initial document record
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        filename=filename,
        file_hash=file_hash,
        status="processing",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    try:
        # Step 4: PDF Text Extraction
        pages = extract_pdf_pages(file_bytes)
        if not pages:
            raise ValueError(f"No extractable text found in PDF document '{filename}'.")

        # Step 5: Token-aware chunking (512 tokens, 128 overlap)
        chunks = chunk_extracted_pages(pages, max_tokens=512, overlap_tokens=128)
        if not chunks:
            raise ValueError(f"Chunking yielded 0 segments for document '{filename}'.")

        # Step 6: Gemini Embeddings
        chunk_texts = [c.content for c in chunks]
        embeddings = await embed_chunks(chunk_texts, task_type="retrieval_document")

        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"Embedding count mismatch: expected {len(chunks)}, got {len(embeddings)}"
            )

        # Step 7: Prepare ChunkRecords
        chunk_records = [
            ChunkRecord(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                document_id=doc.id,
                content=chunk.content,
                embedding=embedding,
                meta={
                    "page": chunk.page_number,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "filename": filename,
                },
                chunk_index=chunk.chunk_index,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]

        # Step 8: Vector Store Upsert
        await vector_store.upsert_chunks(tenant_id=tenant_id, chunks=chunk_records)

        # Step 9: Mark as ready
        doc.status = "ready"
        await db.commit()
        await db.refresh(doc)

        logger.info(
            "Document ingestion completed successfully",
            extra={
                "tenant_id": str(tenant_id),
                "document_id": str(doc.id),
                "chunks_count": len(chunk_records),
            },
        )
        return doc

    except Exception as exc:
        logger.error(
            f"Document ingestion failed: {exc}",
            extra={"tenant_id": str(tenant_id), "document_id": str(doc.id)},
        )
        doc.status = "failed"
        await db.commit()
        await db.refresh(doc)
        raise
