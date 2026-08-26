FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for security tools
RUN apt-get update && apt-get install -y \
    nmap nikto dnsmasq curl wget git \
    postgresql-client openssh-client \
    build-essential libssl-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY gacyber_toolkit/ ./gacyber_toolkit/

# Create necessary directories
RUN mkdir -p data logs backups

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
