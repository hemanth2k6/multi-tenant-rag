"""RAG pipeline services: extraction, chunking, embedding, ingestion, retrieval."""

from app.services.rag.chunker import TextChunk, chunk_extracted_pages
from app.services.rag.embedder import embed_chunks, generate_answer
from app.services.rag.extractor import ExtractedPage, extract_pdf_pages
from app.services.rag.ingestion import DuplicateDocumentError, ingest_document
from app.services.rag.retriever import retrieve_and_answer

__all__ = [
    "DuplicateDocumentError",
    "ExtractedPage",
    "TextChunk",
    "chunk_extracted_pages",
    "embed_chunks",
    "extract_pdf_pages",
    "generate_answer",
    "ingest_document",
    "retrieve_and_answer",
]
