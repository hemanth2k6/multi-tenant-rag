"""PDF text extraction service with corrupted document detection and thread offloading."""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError:  # Fallback for environments with PyPDF2
    from PyPDF2 import PdfReader  # type: ignore[no-redef]
    from PyPDF2.errors import PdfReadError  # type: ignore[no-redef]

from app.core.exceptions import CorruptedPDFError, EmptyDocumentError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExtractedPage:
    """Represents text extracted from a single PDF page."""

    page_number: int  # 1-indexed
    text: str


def extract_pdf_pages(file_bytes: bytes) -> list[ExtractedPage]:
    """Synchronous CPU-bound extraction of text from PDF bytes.

    Raises:
        CorruptedPDFError: If PDF structure is invalid, truncated, encrypted, or corrupted.
        EmptyDocumentError: If PDF parses but contains no extractable text.
    """
    if not file_bytes:
        raise EmptyDocumentError("Cannot extract text from empty file payload.")

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        # Validate that page count can be read (catches malformed xref tables)
        num_pages = len(reader.pages)
        if num_pages == 0:
            raise EmptyDocumentError("PDF document has 0 pages.")
    except (PdfReadError, EOFError, ValueError, Exception) as exc:
        logger.warning(f"Corrupted PDF structure detected: {exc}")
        raise CorruptedPDFError(f"Corrupted or invalid PDF format: {exc}") from exc

    pages: list[ExtractedPage] = []
    for idx in range(num_pages):
        try:
            page = reader.pages[idx]
            page_text = page.extract_text() or ""
            cleaned = page_text.strip()
            if cleaned:
                pages.append(ExtractedPage(page_number=idx + 1, text=cleaned))
        except Exception as exc:
            logger.warning(f"Failed to extract text from page {idx + 1}: {exc}")

    if not pages:
        logger.warning("PDF document parsed successfully but contains no extractable text")
        raise EmptyDocumentError("Uploaded PDF contains no extractable text or is image-only.")

    return pages


async def extract_pdf_pages_async(file_bytes: bytes) -> list[ExtractedPage]:
    """Asynchronously offload CPU-bound PDF extraction to a worker thread."""
    return await asyncio.to_thread(extract_pdf_pages, file_bytes)
