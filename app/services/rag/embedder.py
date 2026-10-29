"""Google Gemini API embedding and generation service."""

from __future__ import annotations

import asyncio
from typing import Any

import google.generativeai as genai

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_configured = False


def _ensure_genai_configured() -> None:
    """Configure the Google Generative AI client once with API key."""
    global _configured
    if not _configured and settings.GEMINI_API_KEY:
        genai.configure(api_key=settings.GEMINI_API_KEY, transport="rest")
        _configured = True


async def embed_chunks(
    texts: list[str],
    task_type: str = "retrieval_document",
) -> list[list[float]]:
    """Compute 768-dimensional embeddings for a batch of text segments using Gemini.

    Args:
        texts: List of text strings to embed.
        task_type: 'retrieval_document' for chunks, 'retrieval_query' for user questions.

    Returns:
        List of 768-dimensional float embedding vectors.
    """
    if not texts:
        return []

    _ensure_genai_configured()

    model_name = f"models/{settings.GEMINI_EMBEDDING_MODEL}"
    try:
        kwargs: dict[str, Any] = {
            "model": model_name,
            "content": texts,
            "task_type": task_type,
        }
        if settings.EMBEDDING_DIM:
            kwargs["output_dimensionality"] = settings.EMBEDDING_DIM
        response = await asyncio.to_thread(genai.embed_content, **kwargs)
    except Exception as exc:
        logger.error(f"Gemini embed_content_async failed: {exc}")
        raise

    raw_embedding = response.get("embedding", [])
    # If a single text was passed, Gemini may return a flat list of floats
    if raw_embedding and isinstance(raw_embedding[0], int | float):
        return [raw_embedding]

    return [list(vec) for vec in raw_embedding]


async def generate_answer(question: str, contexts: list[str]) -> str:
    """Generate a synthesized answer using Gemini based solely on retrieved context."""
    _ensure_genai_configured()

    formatted_context = "\n\n---\n\n".join(
        f"[Source {idx + 1}]\n{ctx}" for idx, ctx in enumerate(contexts)
    )

    prompt = (
        "You are an expert AI assistant answering questions based strictly on the provided "
        "document excerpts.\n\n"
        "Guidelines:\n"
        "1. Base your answer solely on the context below.\n"
        "2. If the context does not contain sufficient information, explicitly state: "
        "'I cannot answer this based on the provided documents.'\n"
        "3. Keep your explanation accurate, clear, and concise.\n\n"
        f"Context:\n{formatted_context}\n\n"
        f"Question:\n{question}\n\n"
        "Answer:"
    )

    model = genai.GenerativeModel(settings.GEMINI_CHAT_MODEL)
    try:
        response = await asyncio.to_thread(model.generate_content, prompt)
        text_content = str(response.text) if hasattr(response, "text") else ""
        return text_content.strip()
    except Exception as exc:
        logger.error(f"Gemini generate_content_async failed: {exc}")
        raise
