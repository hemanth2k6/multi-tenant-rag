# Multi-Tenant RAG API for SaaS

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg?logo=postgresql)](https://github.com/pgvector/pgvector)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D.svg?logo=redis)](https://redis.io)
[![Gemini](https://img.shields.io/badge/Google%20Gemini-text--embedding--004%20%7C%20gemini--2.0--flash-8E75C2.svg)](https://ai.google.dev/)
[![CI](https://github.com/hemanth2k6/multi-tenant-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/hemanth2k6/multi-tenant-rag/actions)

A production-ready, asynchronous backend service built from scratch for Multi-Tenant Software-as-a-Service (SaaS) platforms. The service enables organizations to securely upload documents, generate high-dimensional vector embeddings, and query their private knowledge base via Retrieval-Augmented Generation (RAG) with cryptographic tenant isolation and distributed rate limiting.

Powered exclusively by **Google Gemini API** (`text-embedding-004` and `gemini-2.0-flash`). No paid vector database required—vector similarity search runs locally on **PostgreSQL 16 + pgvector**.

---

## Architecture

```
+---------------------------------------------------------------------+
|                          FastAPI Application                         |
|                                                                     |
|  POST /api/v1/documents/upload   POST /api/v1/query                 |
|  GET  /api/v1/documents          GET  /health  GET /health/ready    |
|                                                                     |
|  +-------------------------------------------------------------+   |
|  |                  Auth + Rate-Limit Layer                     |   |
|  |  Bearer API key -> SHA-256 lookup -> Tenant resolved         |   |
|  |  Redis sliding-window Lua script (10/60s free, 100/60s pro) |   |
|  +-------------------------------------------------------------+   |
|                                                                     |
|  +----------------------+   +----------------------------------+   |
|  |   Ingestion Pipeline |   |       Query Pipeline             |   |
|  |  PDF -> PyPDF2       |   |  Query -> Gemini embed           |   |
|  |  -> tiktoken chunks  |   |  -> pgvector cosine search       |   |
|  |  -> Gemini embed     |   |  -> defence-in-depth filter      |   |
|  |  -> pgvector upsert  |   |  -> Gemini chat answer           |   |
|  +----------------------+   +----------------------------------+   |
+---------------------------------------------------------------------+
         |                                    |
   +-----+------+                      +------+------+
   | PostgreSQL  |                      |   Redis 7   |
   | + pgvector  |                      | Rate limits |
   |  (vectors,  |                      |   + cache   |
   |   metadata) |                      +-------------+
   +-------------+
```

---

## Architectural Decisions & Design Rationale

### 1. Multi-Tenant Isolation & Defence-in-Depth
- **Database-Level Isolation**: Every tenant-scoped entity (`api_keys`, `documents`, `chunks`) enforces a strict Foreign Key relationship to `tenants.id` with `ON DELETE CASCADE`.
- **Query-Level Scoping**: Vector similarity queries always enforce tenant separation in the SQL `WHERE` clause:
  ```sql
  SELECT id, content, 1 - (embedding <=> CAST(:query_vector AS vector)) AS score
  FROM chunks
  WHERE tenant_id = :tenant_id
  ORDER BY embedding <=> CAST(:query_vector AS vector) ASC
  LIMIT :top_k;
  ```
- **Post-Retrieval Defence-in-Depth Filter**: Even after scoped SQL execution, an application-level filter verifies that every retrieved chunk matches `chunk.tenant_id == authenticated_tenant.id`. Any anomalous cross-tenant leakage is instantly dropped and logged as a critical security alert.
- **Cryptographic Authentication**: Tenant identity is resolved **solely** from the `Authorization: Bearer <token>` header—never from request bodies or URL parameters. Raw keys are never stored; only their cryptographic SHA-256 digest is persisted.

### 2. Distributed Sliding-Window Rate Limiting (Atomic Redis Lua)
- Rate limiting operates on an atomic **Redis sorted set (ZSET)** using an embedded Lua script (`rate_limit.lua`).
- Timestamps represent both score and member elements (`ZREMRANGEBYSCORE` + `ZCARD` + `ZADD`).
- Prevents burst boundaries common in fixed-window limiters.
- Executed as a FastAPI dependency (`rate_limited_tenant`) that executes **after** tenant authentication, ensuring limits apply dynamically per tenant tier:
  - **Free Tier**: 10 requests / 60 seconds
  - **Premium Tier**: 100 requests / 60 seconds
- Exceeding quotas returns HTTP 429:
  ```json
  {
    "error": "rate_limit_exceeded",
    "plan": "free",
    "limit": 10
  }
  ```

### 3. Native pgvector without Driver Type Pitfalls
- `asyncpg` frequently encounters codec mismatch errors when attempting to register custom postgres extensions such as `pgvector`.
- To guarantee zero-configuration reliability across all environments, this service performs vector inserts and distance operations using explicit SQL casting:
  ```sql
  INSERT INTO chunks (..., embedding)
  VALUES (..., CAST(:embedding AS vector))
  ```
  Vectors are serialized as standard formatted literals (`[0.123, -0.456, ...]`), allowing standard text parameter binding while PostgreSQL executes HNSW index lookups natively.

### 4. Fully Asynchronous Pipeline
- All I/O operations—HTTP request handling, database queries via `SQLAlchemy 2.0` + `asyncpg`, Redis Lua evaluation, and Gemini API calls—are 100% non-blocking.
- Connection pooling with pre-ping validation ensures resiliency against dropped socket connections.

---

## API Reference

| Method | Endpoint | Auth | Description |
|:-------|:---------|:----:|:------------|
| `GET` | `/health` | No | Liveness probe verifying HTTP service availability. |
| `GET` | `/health/ready` | No | Readiness probe testing PostgreSQL and Redis connectivity. |
| `POST` | `/api/v1/documents/upload` | Bearer Key | Upload and index a PDF file for the authenticated tenant. |
| `GET` | `/api/v1/documents` | Bearer Key | List all indexed documents belonging to the authenticated tenant. |
| `POST` | `/api/v1/query` | Bearer Key | Execute semantic RAG search and synthesize an answer. |

---

## Getting Started

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/)
- Python 3.12 (if developing locally)
- A [Google Gemini API Key](https://aistudio.google.com/)

### 1. Environment Configuration

Copy the example environment template:
```bash
cp .env.example .env
```

Edit `.env` and set your Gemini API key:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
```

### 2. Run with Docker Compose

Start PostgreSQL 16 (pgvector), Redis 7, and the FastAPI application:
```bash
make up
```

Verify service readiness:
```bash
curl http://localhost:8000/health/ready
```
```json
{
  "status": "ok",
  "database": "connected",
  "redis": "connected"
}
```

### 3. Seed an Initial Tenant & Generate API Key

Run the seed script to create a tenant organization and display a one-time API key:
```bash
make seed
```
Output:
```text
============================================================
🎉 Tenant and API Key created successfully!
============================================================
 Tenant ID:   98a72b0c-4e89-4672-873b-f472851cf2a1
 Name:        Acme Corp
 Plan:        free
 Key Prefix:  rag_x8Y1
------------------------------------------------------------
 Raw API Key: rag_x8Y1...32_character_token
------------------------------------------------------------
⚠️  SAVE THIS KEY! It is never stored and cannot be retrieved again.
```

### 4. Ingest a PDF Document

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer <YOUR_RAW_API_KEY>" \
  -F "file=@sample.pdf"
```

Response (HTTP 201):
```json
{
  "id": "1b08f4cb-2947-49f3-8b7a-9a9da8c973a0",
  "filename": "sample.pdf",
  "status": "ready",
  "message": "Document uploaded, chunked, embedded, and indexed successfully."
}
```

*Note: Uploading the identical document twice for the same tenant returns `HTTP 409 Conflict` (SHA-256 deduplication).*

### 5. Query the Knowledge Base

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer <YOUR_RAW_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What does the document say about the quarterly targets?",
    "top_k": 3
  }'
```

Response (HTTP 200):
```json
{
  "answer": "According to the report, the Q3 target was exceeded by 14% primarily driven by enterprise subscription growth.",
  "sources": [
    {
      "chunk_id": "73c1d9b4-f3a2-4a0b-936d-1bf88d169ac4",
      "document_id": "1b08f4cb-2947-49f3-8b7a-9a9da8c973a0",
      "content": "Quarterly Performance: Q3 financial metrics exceeded targets by 14%...",
      "score": 0.912,
      "meta": {
        "page": 2,
        "char_start": 412,
        "char_end": 745,
        "filename": "sample.pdf"
      }
    }
  ],
  "question": "What does the document say about the quarterly targets?"
}
```

---

## Local Development & Testing

### Running Commands via Makefile

```bash
# Run database migrations locally
make migrate

# Run API server with uvicorn auto-reload
make run

# Run full pytest suite with monkeypatched AI calls
make test

# Run Ruff linter and Mypy strict type checker
make lint

# Run code formatters (ruff format + black)
make format
```

### Test Suite

Tests run in complete isolation with monkeypatched Gemini calls:
```bash
pytest -v
```
```text
tests/test_auth.py::test_unauthenticated_request_rejected PASSED        [ 10%]
tests/test_auth.py::test_invalid_api_key_rejected PASSED                [ 20%]
tests/test_auth.py::test_valid_api_key_accepted PASSED                  [ 30%]
tests/test_health.py::test_health_liveness PASSED                       [ 40%]
tests/test_health.py::test_health_readiness_healthy PASSED             [ 50%]
tests/test_health.py::test_health_readiness_db_failure PASSED           [ 60%]
tests/test_ingestion.py::test_pdf_upload_and_listing_roundtrip PASSED  [ 70%]
tests/test_ingestion.py::test_duplicate_pdf_upload_rejected PASSED     [ 80%]
tests/test_ingestion.py::test_rag_query_pipeline PASSED                 [ 90%]
tests/test_rate_limit.py::test_free_tier_sliding_window_rate_limiting PASSED [100%]
```

---

## Security Compliance

1. **Zero Raw Key Storage**: Keys are hashed via `hashlib.sha256` before persistence.
2. **Key Prefix Masking**: Logs display only the first 8 characters (`rag_x8Y1...`).
3. **No SQL Interpolation**: All SQL operations use bound parameters or explicit type-casted parameter maps.
4. **Context Propagation**: Request logs include `tenant_id` structured metadata for audit trails.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
