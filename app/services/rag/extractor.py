"""PDF text extraction service using PyPDF2."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PyPDF2 import PdfReader

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExtractedPage:
    """Represents text extracted from a single PDF page."""

    page_number: int  # 1-indexed
    text: str


def extract_pdf_pages(file_bytes: bytes) -> list[ExtractedPage]:
    """Extract text from PDF byte content.

    Returns:
        List of ExtractedPage containing the page number and non-empty text.

    Raises:
        ValueError: If PDF cannot be parsed or contains no extractable text.
    """
    if not file_bytes:
        raise ValueError("Cannot extract text from empty file bytes")

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        logger.error(f"Failed to parse PDF document: {exc}")
        raise ValueError(f"Invalid PDF format: {exc}") from exc

    pages: list[ExtractedPage] = []
    for idx, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
            cleaned = page_text.strip()
            if cleaned:
                pages.append(ExtractedPage(page_number=idx + 1, text=cleaned))
        except Exception as exc:
            logger.warning(f"Failed to extract text from page {idx + 1}: {exc}")

    if not pages:
        logger.warning("PDF parsing completed but yielded zero non-empty pages")

    return pages
