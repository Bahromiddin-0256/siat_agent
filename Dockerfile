# Multi-stage Dockerfile for SDMX Agent

# Stage 1: Builder - Install dependencies
FROM python:3.10-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./

# Install Python dependencies
RUN uv sync

# Stage 2: Runtime - Create final image
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

# Copy JSON data files (for init container to use)
COPY --chown=appuser:appuser jsons/main.json ./jsons/main.json
COPY --chown=appuser:appuser jsons/sdmxs/ ./jsons/sdmxs/

# Set environment variables
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER appuser

# Expose application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run the application
CMD ["python", "main.py"]
