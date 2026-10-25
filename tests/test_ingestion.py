"""End-to-end ingestion and query pipeline tests."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import make_minimal_pdf


@pytest.mark.asyncio
async def test_pdf_upload_and_listing_roundtrip(
    async_client: httpx.AsyncClient,
    test_headers: dict[str, str],
) -> None:
    """Verify PDF upload, chunking, embedding, vector storage, and listing."""
    pdf_content = make_minimal_pdf("Antigravity Multi-Tenant Knowledge Base Introduction.")

    files = {
        "file": ("rag_manual.pdf", pdf_content, "application/pdf"),
    }

    # 1. Upload PDF
    upload_response = await async_client.post(
        "/api/v1/documents/upload",
        headers=test_headers,
        files=files,
    )
    assert upload_response.status_code == 201
    upload_data = upload_response.json()
    assert upload_data["filename"] == "rag_manual.pdf"
    assert upload_data["status"] == "ready"
    assert "id" in upload_data

    # 2. List documents
    list_response = await async_client.get(
        "/api/v1/documents",
        headers=test_headers,
    )
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert list_data["total"] >= 1
    filenames = [doc["filename"] for doc in list_data["documents"]]
    assert "rag_manual.pdf" in filenames


@pytest.mark.asyncio
async def test_duplicate_pdf_upload_rejected(
    async_client: httpx.AsyncClient,
    test_headers: dict[str, str],
) -> None:
    """Verify duplicate upload for same tenant is rejected with 409 Conflict."""
    pdf_content = make_minimal_pdf("Unique Deduplication Test Content 12345.")

    files1 = {"file": ("report.pdf", pdf_content, "application/pdf")}
    first_upload = await async_client.post(
        "/api/v1/documents/upload",
        headers=test_headers,
        files=files1,
    )
    assert first_upload.status_code == 201

    # Second upload with identical content
    files2 = {"file": ("report_copy.pdf", pdf_content, "application/pdf")}
    duplicate_upload = await async_client.post(
        "/api/v1/documents/upload",
        headers=test_headers,
        files=files2,
    )
    assert duplicate_upload.status_code == 409


@pytest.mark.asyncio
async def test_rag_query_pipeline(
    async_client: httpx.AsyncClient,
    test_headers: dict[str, str],
) -> None:
    """Verify RAG query endpoint retrieves chunks and synthesizes answer."""
    pdf_content = make_minimal_pdf("Google Gemini powers multi-tenant RAG applications.")

    # Ingest document first
    await async_client.post(
        "/api/v1/documents/upload",
        headers=test_headers,
        files={"file": ("knowledge.pdf", pdf_content, "application/pdf")},
    )

    # Query knowledge base
    query_payload = {
        "question": "What powers multi-tenant RAG applications?",
        "top_k": 3,
    }
    response = await async_client.post(
        "/api/v1/query",
        headers=test_headers,
        json=query_payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "sources" in data
    assert data["question"] == query_payload["question"]
    assert len(data["sources"]) >= 1
