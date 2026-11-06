"""Google Gemini API embedding and generation service with retry and timeout protection."""

from __future__ import annotations

import asyncio
from typing import Any

import google.generativeai as genai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import settings
from app.core.exceptions import EmbeddingServiceError, EmbeddingTimeoutError
from app.core.logging import get_logger

logger = get_logger(__name__)

_configured = False
DEFAULT_TIMEOUT_SECONDS = 15.0


def _ensure_genai_configured() -> None:
    """Configure the Google Generative AI client once with API key."""
    global _configured
    if not _configured and settings.GEMINI_API_KEY:
        genai.configure(api_key=settings.GEMINI_API_KEY, transport="rest")
        _configured = True


def _should_retry_exception(exc: BaseException) -> bool:
    """Determine whether an exception is transient and eligible for retry."""
    # Never retry cancellation or programming errors
    if isinstance(exc, asyncio.CancelledError | TypeError | ValueError):
        return False
    # Transient network or provider errors
    err_str = str(exc).lower()
    return any(keyword in err_str for keyword in ("429", "503", "timeout", "resource_exhausted", "unavailable"))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1.0, max=8.0),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_gemini_embed(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Execute synchronous call to Gemini embed_content inside retry boundary."""
    return genai.embed_content(**kwargs)  # type: ignore[no-any-return]


async def embed_chunks(
    texts: list[str],
    task_type: str = "retrieval_document",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[list[float]]:
    """Compute 768-dimensional embeddings for a batch of text segments using Gemini.

    Protected by exponential backoff, jitter, and strict deadline timeouts.

    Args:
        texts: List of text strings to embed.
        task_type: 'retrieval_document' for chunks, 'retrieval_query' for queries.
        timeout_seconds: Timeout budget per attempt.

    Returns:
        List of 768-dimensional float embedding vectors.

    Raises:
        EmbeddingTimeoutError: If the Gemini API call exceeds timeout budget.
        EmbeddingServiceError: If the Gemini API fails with an unrecoverable error.
    """
    if not texts:
        return []

    _ensure_genai_configured()

    model_name = f"models/{settings.GEMINI_EMBEDDING_MODEL}"
    kwargs: dict[str, Any] = {
        "model": model_name,
        "content": texts,
        "task_type": task_type,
    }
    if settings.EMBEDDING_DIM:
        kwargs["output_dimensionality"] = settings.EMBEDDING_DIM

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_call_gemini_embed, kwargs),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        logger.error(f"Gemini embedding API timed out after {timeout_seconds}s")
        raise EmbeddingTimeoutError(
            f"Vector embedding API timed out after {timeout_seconds} seconds."
        ) from exc
    except Exception as exc:
        logger.error(f"Gemini embedding API failed: {exc}")
        raise EmbeddingServiceError(f"Vector embedding provider error: {exc}") from exc

    raw_embedding = response.get("embedding", [])
    # If a single text was passed, Gemini may return a flat list of floats
    if raw_embedding and isinstance(raw_embedding[0], int | float):
        return [raw_embedding]

    return [list(vec) for vec in raw_embedding]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1.0, max=8.0),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_gemini_generate(model: genai.GenerativeModel, prompt: str) -> str:
    """Execute synchronous call to Gemini generate_content inside retry boundary."""
    res = model.generate_content(prompt)
    return str(res.text).strip() if hasattr(res, "text") and res.text else ""


async def generate_answer(
    question: str,
    contexts: list[str],
    timeout_seconds: float = 30.0,
) -> str:
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
        return await asyncio.wait_for(
            asyncio.to_thread(_call_gemini_generate, model, prompt),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        logger.error(f"Gemini chat generation timed out after {timeout_seconds}s")
        raise EmbeddingTimeoutError("LLM response generation timed out.") from exc
    except Exception as exc:
        logger.error(f"Gemini generate_content failed: {exc}")
        raise EmbeddingServiceError(f"LLM generation failed: {exc}") from exc
