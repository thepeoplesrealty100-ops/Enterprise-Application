FROM python:3.11-slim

WORKDIR /app

# System deps. Note: `nikto` is not in Debian trixie apt — omit it.
# nmap is available; nuclei/gobuster can be added later via official binaries if needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    curl \
    wget \
    git \
    ca-certificates \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Application code
COPY backend/ /app/backend/
COPY gacyber_toolkit/ /app/gacyber_toolkit/

RUN mkdir -p /app/data /app/logs /app/backups

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend
ENV DUCKDB_PATH=/app/data/jakal.duckdb

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
