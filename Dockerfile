# Multi-stage Dockerfile for SDMX Agent

# Stage 1: Builder — install uv and sync dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build tools and uv. Switch apt mirrors to HTTPS first — the
# HTTP mirrors get reset by some firewalls/proxies.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://security.debian.org|https://security.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        curl \
        ca-certificates \
    && pip install --no-cache-dir uv \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files (lockfile included so --frozen works)
COPY pyproject.toml uv.lock ./

# Persistent uv cache across builds via BuildKit cache mount, seeded from
# the host's ~/.cache/uv on first build (passed via compose additional_contexts).
# UV_LINK_MODE=copy avoids hardlink errors when cache is on a different fs.
ENV UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv,id=siat-uv-cache \
    --mount=type=bind,from=host-uv-cache,target=/host-uv-cache,readonly \
    if [ -z "$(ls -A /root/.cache/uv 2>/dev/null)" ] && [ -d /host-uv-cache ]; then \
        echo "Seeding BuildKit uv cache from host..."; \
        cp -rn /host-uv-cache/. /root/.cache/uv/ 2>/dev/null || true; \
    fi && \
    uv sync --frozen --no-dev

# Stage 2: Runtime — minimal final image
FROM python:3.12-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/chroma_db /app/jsons && \
    chown -R appuser:appuser /app

# Copy the uv-managed venv from builder stage
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code
COPY --chown=appuser:appuser core/ ./core/
COPY --chown=appuser:appuser tools/ ./tools/
COPY --chown=appuser:appuser static/ ./static/
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser pyproject.toml ./

# Copy JSON data files
COPY --chown=appuser:appuser jsons/main.json ./jsons/main.json
COPY --chown=appuser:appuser jsons/sdmxs/ ./jsons/sdmxs/

# Set environment variables
ENV PATH=/app/.venv/bin:$PATH \
    VIRTUAL_ENV=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_PORT=8000

# Switch to non-root user
USER appuser

# Expose application port (matches APP_PORT default)
EXPOSE 8000

# Health check — uses APP_PORT env var so it works with non-default ports
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c \
        "import urllib.request, os; \
         port = os.environ.get('APP_PORT', '8000'); \
         urllib.request.urlopen(f'http://localhost:{port}/health', timeout=5)" \
    || exit 1

# Run the application
CMD ["python", "main.py"]
