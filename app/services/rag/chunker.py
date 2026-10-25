"""Token-aware text chunking using tiktoken."""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

from app.services.rag.extractor import ExtractedPage


@dataclass
class TextChunk:
    """Represents a token-bounded text segment with provenance metadata."""

    content: str
    page_number: int
    char_start: int
    char_end: int
    chunk_index: int


def chunk_extracted_pages(
    pages: list[ExtractedPage],
    max_tokens: int = 512,
    overlap_tokens: int = 128,
    encoding_name: str = "cl100k_base",
) -> list[TextChunk]:
    """Chunk extracted pages using a token-aware sliding window.

    Args:
        pages: List of ExtractedPage from PDF extractor.
        max_tokens: Maximum tokens per chunk (default 512).
        overlap_tokens: Overlap between consecutive chunks (default 128).
        encoding_name: tiktoken encoding to use (default cl100k_base).

    Returns:
        List of TextChunk instances with page and character boundaries.
    """
    enc = tiktoken.get_encoding(encoding_name)
    chunks: list[TextChunk] = []
    chunk_index = 0
    step_tokens = max(1, max_tokens - overlap_tokens)

    for page in pages:
        tokens = enc.encode(page.text)
        total_tokens = len(tokens)

        if total_tokens == 0:
            continue

        if total_tokens <= max_tokens:
            chunks.append(
                TextChunk(
                    content=page.text,
                    page_number=page.page_number,
                    char_start=0,
                    char_end=len(page.text),
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
            continue

        start_token_idx = 0
        while start_token_idx < total_tokens:
            end_token_idx = min(start_token_idx + max_tokens, total_tokens)
            window_tokens = tokens[start_token_idx:end_token_idx]
            chunk_text = enc.decode(window_tokens).strip()

            if chunk_text:
                char_start = page.text.find(chunk_text[:30]) if len(chunk_text) >= 30 else 0
                char_start = max(0, char_start)
                char_end = char_start + len(chunk_text)

                chunks.append(
                    TextChunk(
                        content=chunk_text,
                        page_number=page.page_number,
                        char_start=char_start,
                        char_end=char_end,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1

            if end_token_idx >= total_tokens:
                break

            start_token_idx += step_tokens

    return chunks
