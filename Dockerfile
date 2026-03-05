# Multi-stage Dockerfile for SDMX Agent

# Stage 1: Builder — install uv and sync dependencies
FROM python:3.10-slim AS builder

WORKDIR /app

# Install build tools and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && pip install --no-cache-dir uv \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./

# Install Python dependencies into a local venv via uv
RUN uv sync --no-dev

# Stage 2: Runtime — minimal final image
FROM python:3.10-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/chroma_db /app/jsons && \
    chown -R appuser:appuser /app

# Copy installed packages from builder stage
COPY --from=builder /root/.local /home/appuser/.local

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
ENV PATH=/home/appuser/.local/bin:$PATH \
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
