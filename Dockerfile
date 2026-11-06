# ==============================================================================
# Multi-Stage Production Dockerfile for Multi-Tenant RAG API
# Compliant with CIS Docker Benchmark & SOC2 Principle of Least Privilege
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build & Dependency Wheel Compilation
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install system compilation tools required for native C extensions (asyncpg, tiktoken)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment to isolate dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Hardened Runtime Container
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install minimal runtime utility (curl for docker/k8s health probes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user and group
RUN groupadd -g 10001 raggroup && \
    useradd -u 10001 -g raggroup -s /bin/bash -m raguser

# Copy virtual environment from builder stage
COPY --from=builder --chown=raguser:raggroup /opt/venv /opt/venv

# Copy application source code with non-root ownership
COPY --chown=raguser:raggroup . /app

# Switch to non-root user for principle of least privilege
USER raguser

EXPOSE 8000

# Healthcheck definition compliant with container orchestrators
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health/ready || exit 1

# Execute database migrations on container start, then run Uvicorn with standard ASGI workers
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
