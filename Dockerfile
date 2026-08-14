# ============================================================================
# JAKAL Enterprise Docker Build - Multi-Stage Optimized
# ============================================================================

# Stage 1: Builder - Compile dependencies
FROM python:3.10-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Build wheel packages
RUN pip install --user --no-cache-dir --no-warn-script-location -r requirements.txt

# ============================================================================
# Stage 2: Runtime - Slim production image
# ============================================================================
FROM python:3.10-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built packages from builder
COPY --from=builder /root/.local /root/.local

# Set Python path
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Copy application code
COPY backend /app/backend
COPY dashboard.html /app/dashboard.html
COPY requirements.txt /app/requirements.txt

# Create required directories
RUN mkdir -p /app/data /app/logs /app/backups && \
    chmod -R 755 /app/data /app/logs /app/backups && \
    chown -R 1000:1000 /app

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
