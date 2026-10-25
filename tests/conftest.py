"""Pytest fixtures and test harnesses for Multi-Tenant RAG API."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import redis.asyncio as aioredis
from httpx import ASGITransport
from sqlalchemy.sql.elements import TextClause

from app.core.config import settings
from app.core.redis import RedisClient, get_redis
from app.core.security import hash_api_key
from app.db.models.api_key import ApiKey
from app.db.models.document import Document
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.main import app


def make_minimal_pdf(text_content: str = "Hello World") -> bytes:
    """Generate a minimal valid 1-page PDF using only standard library."""
    stream = f"BT /F1 12 Tf 72 712 Td ({text_content}) Tj ET\n"
    stream_len = len(stream.encode("latin-1"))

    body = (
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        "3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        "/MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n"
        "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        f"5 0 obj\n<< /Length {stream_len} >>\nstream\n{stream}endstream\nendobj\n"
    )
    header = "%PDF-1.4\n"
    content = header + body

    xref = (
        "xref\n"
        "0 6\n"
        "0000000000 65535 f \n"
        "0000000009 00000 n \n"
        "0000000058 00000 n \n"
        "0000000115 00000 n \n"
        "0000000242 00000 n \n"
        "0000000318 00000 n \n"
        "trailer\n<< /Size 6 /Root 1 0 R >>\n"
        f"startxref\n{len(content.encode('latin-1'))}\n%%EOF\n"
    )
    return (content + xref).encode("latin-1")


class MockResult:
    """Simulates SQLAlchemy Result wrapper."""

    def __init__(self, data: list[Any]) -> None:
        self._data = data

    def scalar_one_or_none(self) -> Any:
        return self._data[0] if self._data else None

    def scalar(self) -> Any:
        return self._data[0] if self._data else None

    def scalars(self) -> MockResult:
        return self

    def all(self) -> list[Any]:
        return list(self._data)

    def fetchall(self) -> list[Any]:
        return list(self._data)


@dataclass
class StoredChunk:
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    embedding: list[float]
    meta: dict[str, Any]
    chunk_index: int


class InMemorySession:
    """In-memory async session tracking entities and raw SQL for tests."""

    def __init__(self) -> None:
        self.tenants: list[Tenant] = []
        self.api_keys: list[ApiKey] = []
        self.documents: list[Document] = []
        self.chunks: list[StoredChunk] = []

    def add(self, instance: Any) -> None:
        if isinstance(instance, Tenant):
            if instance not in self.tenants:
                self.tenants.append(instance)
        elif isinstance(instance, ApiKey):
            if instance not in self.api_keys:
                self.api_keys.append(instance)
        elif isinstance(instance, Document) and instance not in self.documents:
            self.documents.append(instance)

    async def commit(self) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: Any) -> None:
        pass

    async def close(self) -> None:
        pass

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> MockResult:
        # 1. Raw SQL: SELECT 1
        if isinstance(statement, TextClause):
            text_str = statement.text.strip()
            if "SELECT 1" in text_str:
                return MockResult([1])

            # Raw SQL: INSERT INTO chunks
            if "INSERT INTO chunks" in text_str and params:
                emb_str = params.get("embedding", "[]")
                emb = [float(x) for x in emb_str.strip("[]").split(",") if x.strip()]
                meta_val = params.get("meta", "{}")
                meta = json.loads(meta_val) if isinstance(meta_val, str) else meta_val

                chunk = StoredChunk(
                    id=uuid.UUID(str(params["id"])),
                    tenant_id=uuid.UUID(str(params["tenant_id"])),
                    document_id=uuid.UUID(str(params["document_id"])),
                    content=params["content"],
                    embedding=emb,
                    meta=meta,
                    chunk_index=int(params["chunk_index"]),
                )
                self.chunks.append(chunk)
                return MockResult([])

            # Raw SQL: SELECT from chunks (vector search)
            if "SELECT" in text_str and "FROM chunks" in text_str and params:
                tid = uuid.UUID(str(params["tenant_id"]))
                top_k = int(params.get("top_k", 5))
                matched = [c for c in self.chunks if c.tenant_id == tid]
                rows = [
                    (c.id, c.tenant_id, c.document_id, c.content, c.meta, c.chunk_index, 0.95)
                    for c in matched[:top_k]
                ]
                return MockResult(rows)

            # Raw SQL: DELETE FROM chunks
            if "DELETE FROM chunks" in text_str and params:
                tid = uuid.UUID(str(params["tenant_id"]))
                did = uuid.UUID(str(params["document_id"]))
                self.chunks = [
                    c for c in self.chunks if not (c.tenant_id == tid and c.document_id == did)
                ]
                return MockResult([])

        stmt_str = str(statement)

        # 2. Query ApiKey
        if "api_keys" in stmt_str:
            # Check params or compiled clause
            matched_key: ApiKey | None = None
            for key in self.api_keys:
                if not key.revoked:
                    matched_key = key
                    break
            return MockResult([matched_key] if matched_key else [])

        # 3. Query Document
        if "documents" in stmt_str:
            if "file_hash" in stmt_str:
                # Deduplication check: check if any document matches params
                return MockResult(self.documents if self.documents else [])
            return MockResult(self.documents)

        return MockResult([])


@pytest.fixture(autouse=True)
def mock_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock Gemini API embedding and chat endpoints for all tests."""
    # 768-dim mock vector
    mock_vector = [0.1] * 768

    async def mock_embed_chunks(
        texts: list[str],
        task_type: str = "retrieval_document",
    ) -> list[list[float]]:
        return [mock_vector for _ in texts]

    async def mock_generate_answer(question: str, contexts: list[str]) -> str:
        return f"Synthesized answer to '{question}' based on {len(contexts)} sources."

    monkeypatch.setattr("app.services.rag.embedder.embed_chunks", mock_embed_chunks)
    monkeypatch.setattr("app.services.rag.embedder.generate_answer", mock_generate_answer)


@pytest.fixture
def in_memory_db() -> InMemorySession:
    """Return an isolated in-memory DB session."""
    return InMemorySession()


@pytest.fixture
def test_tenant() -> Tenant:
    return Tenant(
        id=uuid.uuid4(),
        name="Acme Corp",
        plan="free",
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def test_raw_key() -> str:
    return "rag_test_secret_key_123456789012345678"


@pytest.fixture
def test_api_key(test_tenant: Tenant, test_raw_key: str) -> ApiKey:
    key = ApiKey(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        key_hash=hash_api_key(test_raw_key),
        prefix=test_raw_key[:8],
        revoked=False,
        created_at=datetime.now(UTC),
    )
    key.tenant = test_tenant
    return key


@pytest.fixture
def test_headers(test_raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {test_raw_key}"}


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    return make_minimal_pdf("Antigravity Multi-Tenant RAG Test Document Content.")


@pytest.fixture
async def redis_client() -> AsyncGenerator[RedisClient, None]:
    client: RedisClient = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )
    yield client
    # Clean up rate limit keys created during test
    keys = await client.keys("rl:*")
    if keys:
        await client.delete(*keys)
    await client.close()


@pytest.fixture
async def async_client(
    in_memory_db: InMemorySession,
    test_tenant: Tenant,
    test_api_key: ApiKey,
    redis_client: RedisClient,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Test client configured with in-memory DB and real Redis."""
    in_memory_db.add(test_tenant)
    in_memory_db.add(test_api_key)

    async def override_get_db() -> AsyncGenerator[InMemorySession, None]:
        yield in_memory_db

    async def override_get_redis() -> AsyncGenerator[aioredis.Redis[str], None]:
        yield redis_client

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
