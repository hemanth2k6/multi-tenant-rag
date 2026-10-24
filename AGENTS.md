# AGENTS.md — Canonical Project Rules

> **All contributors and AI agents must read this file before writing any code.**  
> `GEMINI.md` at the repo root points here.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Stack](#2-stack)
3. [Architecture](#3-architecture)
4. [Success Criteria (Acceptance Checklist)](#4-success-criteria-acceptance-checklist)
5. [Commands](#5-commands)
6. [Code Style](#6-code-style)
7. [Security Rules](#7-security-rules)
8. [Git Rules](#8-git-rules)
9. [Environment Variables](#9-environment-variables)
10. [Testing Strategy](#10-testing-strategy)

---

## 1. Project Overview

**Multi-Tenant RAG API for SaaS** — a production-ready backend that allows multiple isolated
tenants to upload PDFs, embed them into a vector database, and query their private knowledge base
using Retrieval-Augmented Generation (RAG).

Each tenant's data is fully isolated: documents, chunks, and vector embeddings are scoped by
`tenant_id` at the database level, the query level, and enforced again post-retrieval as a
defence-in-depth check.

---

## 2. Stack

| Layer              | Technology                                      |
|--------------------|-------------------------------------------------|
| Language           | Python 3.12                                     |
| Web Framework      | FastAPI (async)                                 |
| ORM                | SQLAlchemy 2.0 (async) + asyncpg                |
| Database           | PostgreSQL 16 + pgvector extension              |
| Cache / Rate Limit | Redis 7                                         |
| Embeddings         | Google Gemini `text-embedding-004` (768 dims)   |
| Chat / Generation  | Google Gemini `gemini-2.0-flash`                |
| Gemini SDK         | `google-generativeai` or `google-genai`         |
| PDF Parsing        | PyPDF2                                          |
| Tokenization       | tiktoken                                        |
| Migrations         | Alembic                                         |
| Containerisation   | Docker + Docker Compose                         |
| Testing            | pytest + pytest-asyncio                         |
| Linting            | ruff (line-length 100)                          |
| Formatting         | black                                           |
| Type Checking      | mypy (strict)                                   |

---

## 3. Architecture

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

## 4. Success Criteria (Acceptance Checklist)

A build is **only accepted** when ALL items below are checked.

### Multi-Tenancy & Isolation
- [ ] Every tenant-scoped table has a `tenant_id` FK.
- [ ] Vector search is scoped by `tenant_id` in the SQL query (`WHERE tenant_id = :tid`).
- [ ] A **defence-in-depth check** after vector search drops any result whose `tenant_id` does not
      match the authenticated tenant.
- [ ] Tenant identity is resolved **only** from the Bearer API key -- never from request body or
      query params.
- [ ] API keys are stored as SHA-256 hashes; raw keys are never persisted.

### RAG Pipeline
- [ ] PDF upload -> `PyPDF2` extraction -> token-aware chunking (`tiktoken`, 512 tokens, 128 overlap)
      -> Gemini embeddings -> pgvector upsert.
- [ ] Duplicate uploads for the same tenant are rejected with HTTP 409 (SHA-256 file hash dedup).
- [ ] Query -> Gemini embedding -> pgvector cosine search -> rerank -> Gemini chat answer.
- [ ] `Chunk` model stores `embedding` as `Vector(768)` and `meta` as JSONB.
- [ ] pgvector operations use **raw SQL** with `CAST(:emb AS vector)` to avoid asyncpg
      type-registration issues.

### Distributed Rate Limiting
- [ ] Redis **sorted-set sliding window** via an **atomic Lua script** (`EVAL`).
- [ ] Free plan: 10 requests / 60s. Premium plan: 100 requests / 60s.
- [ ] Implemented as a FastAPI **dependency** (`rate_limited_tenant`) that runs **after** auth,
      not as middleware.
- [ ] Returns HTTP 429 with `{"error":"rate_limit_exceeded","plan":...,"limit":...}`.

### DevOps & Observability
- [ ] `/health` (liveness) and `/health/ready` (Postgres + Redis checks) endpoints.
- [ ] Structured JSON logging with `tenant_id` when available.
- [ ] `docker-compose.yml` runs API + Postgres (pgvector) + Redis with health checks.
- [ ] `alembic upgrade head` runs automatically on container start.
- [ ] CI workflow (GitHub Actions) runs ruff, mypy, `alembic upgrade head`, and pytest against
      real Postgres + Redis services.

### Testing
- [ ] `pytest -q` passes with tests for: health, auth (401/200), rate limiting (10x200 then 429),
      and an ingestion roundtrip (PDF upload -> list documents) with Gemini calls monkeypatched.
- [ ] Tests use an in-test minimal valid PDF generator (no external fixtures).

---

## 5. Commands

```bash
# Start the full stack (Postgres, Redis, API) in Docker
make up

# Run Alembic migrations inside the running API container
make migrate

# Seed a test tenant and print the raw API key to stdout
make seed

# Run the API locally (outside Docker) with uvicorn auto-reload
make run

# Run the full test suite
make test

# Run ruff linter + mypy type checker
make lint
```

All make targets assume a `.env` file exists (copy from `.env.example`).

---

## 6. Code Style

| Tool      | Config                                      |
|-----------|---------------------------------------------|
| ruff      | `line-length = 100`, all default rule sets  |
| black     | `line-length = 100`                         |
| mypy      | `strict = true`                             |
| isort     | handled by ruff (`I` rule set)              |

- **Async everywhere**: all DB access uses `async with session` via `AsyncSession`.
- **Typed everything**: every function must have full type annotations.
- **No bare `except`**: always catch specific exceptions.
- **Pydantic v2**: use `model_config = ConfigDict(...)` -- not the old `class Config`.
- **SQLAlchemy 2.0 style**: use `select()`, `scalars()`, `execute()` -- never the legacy Query API.

---

## 7. Security Rules

1. **Never log raw API keys.** Only log the key prefix (first 8 chars) for debugging.
2. **Never commit `.env`.** It is in `.gitignore`. Use `.env.example` with placeholder values.
3. **Tenant context comes only from auth.** The `tenant_id` used in any DB query must be the one
   resolved from the verified Bearer token. Never trust `tenant_id` from request body or params.
4. **SHA-256 all keys.** Raw API keys are generated once, shown to the user once, and never stored.
   Only `hashlib.sha256(key.encode()).hexdigest()` is stored in the `api_keys` table.
5. **Defence in depth.** After every pgvector search, filter results again in Python to ensure
   `chunk.tenant_id == authenticated_tenant.id`. Log and drop any mismatches as a security alert.
6. **No SQL interpolation.** Always use SQLAlchemy bound parameters or `text()` with `:param`.

---

## 8. Git Rules

### Commit Message Format (Conventional Commits)

```
<type>(<scope>): <short imperative summary>

[optional body]
[optional footer]
```

**Types:** `feat`, `fix`, `chore`, `test`, `docs`, `ci`, `build`, `refactor`, `perf`
**Scopes:** `core`, `db`, `models`, `schemas`, `auth`, `ratelimit`, `vector`, `rag`, `api`, `app`,
`scripts`, `docker`, `ci`

### Rules
- Each commit must leave the repo **importable and lint-clean**.
- Commit in the order listed in the implementation plan.
- Run `ruff check app tests` and `pytest -q` before every push.
- Never force-push to `main`.
- PR titles follow the same Conventional Commits format.

### Commit Sequence
```
1.  chore: scaffold project tooling and dependencies
2.  feat(core): add pydantic settings and json logging
3.  feat(db): add async sqlalchemy engine and session
4.  feat(models): add Tenant, ApiKey, Document, Chunk models
5.  feat(db): configure alembic with initial migration and pgvector extension
6.  feat(schemas): add request/response pydantic models
7.  feat(core): add api key hashing and redis client
8.  feat(ratelimit): add distributed sliding-window limiter via redis lua
9.  feat(auth): add tenant resolution and rate-limited dependency
10. feat(vector): add pgvector and pinecone backends behind interface
11. feat(rag): add pdf extraction, chunking, and gemini embeddings
12. feat(rag): add ingestion pipeline and retriever with defence-in-depth check
13. feat(api): add documents, query, and health endpoints
14. feat(app): wire fastapi application
15. feat(scripts): add tenant+key seed script
16. test: add fixtures and integration tests for auth, rate limit, ingestion
17. build(docker): add Dockerfile and compose stack with pgvector and redis
18. ci: add github actions workflow
19. docs: finalize README with setup, API, and design decisions
```

---

## 9. Environment Variables

| Variable                | Description                                    | Default / Example                             |
|-------------------------|------------------------------------------------|-----------------------------------------------|
| `DATABASE_URL`          | Async Postgres DSN                             | `postgresql+asyncpg://rag_user:rag_pass@...`  |
| `REDIS_URL`             | Redis DSN                                      | `redis://localhost:6379/0`                    |
| `SECRET_KEY`            | App secret (token signing etc.)                | `change-me-in-production`                     |
| `GEMINI_API_KEY`        | Google Gemini API key                          | `your-key-here`                               |
| `GEMINI_EMBEDDING_MODEL`| Gemini embedding model name                    | `text-embedding-004`                          |
| `GEMINI_CHAT_MODEL`     | Gemini chat model name                         | `gemini-2.0-flash`                            |
| `EMBEDDING_DIM`         | Embedding vector dimensions                    | `768`                                         |
| `VECTOR_BACKEND`        | Vector store backend (`pgvector`/`pinecone`)   | `pgvector`                                    |
| `PINECONE_API_KEY`      | Pinecone API key (optional)                    | _(empty)_                                     |
| `PINECONE_INDEX_NAME`   | Pinecone index name (optional)                 | _(empty)_                                     |
| `DEBUG`                 | Enable debug mode                              | `false`                                       |
| `LOG_LEVEL`             | Logging level                                  | `INFO`                                        |

---

## 10. Testing Strategy

- **Framework**: `pytest` + `pytest-asyncio` (mode: `asyncio_mode = "auto"`).
- **Database**: A real PostgreSQL test database with pgvector; migrations are applied before the
  suite runs (`alembic upgrade head`).
- **External services**: Gemini API calls (`embed_chunks`, `generate_answer`) are **monkeypatched**
  in all tests -- no real API calls are made in CI.
- **PDF fixture**: Tests generate a minimal valid in-memory PDF using only the stdlib -- no external
  fixture files.
- **Test isolation**: Each test uses a database transaction that is rolled back after the test, or
  uses a dedicated test schema.
- **Coverage targets**: health, auth (401/200), rate limiting (10x200 then 429),
  ingestion roundtrip.
