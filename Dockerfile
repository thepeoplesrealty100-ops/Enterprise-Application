# ─────────────────────────────────────────────────────────────────────────────
# JAKAL — single-stage image (FastAPI backend + the vanilla-JS operator UI)
#
# A "Response Console" build stage (Node/Vite, served at /console) used to
# live here. Removed: frontend/ on this branch has no package.json or
# package-lock.json for it to build from -- COPY frontend/package.json
# would fail a fresh `docker build` outright -- and nothing in app.py
# mounts /console or reads /app/frontend/dist, so even a successful build
# of that stage would produce an asset nothing ever serves. If that
# console is revived later, restore this stage deliberately alongside the
# app.py route that serves it, not as a side effect of an unrelated fix.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# System deps. Note: `nikto` is not in Debian trixie apt — omit it.
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

# Frontend (served by FastAPI at / so UI + API share one origin — no CORS pain)
COPY index.html integration.js world_land_map.json /app/frontend/
# app.py mounts /js from FRONTEND_DIR/js specifically (operator-console.js,
# jakal-controls.js, jakal-live-data.js) -- this line was previously
# missing, so that directory never existed in the image and app.py logged
# "Frontend js/ directory missing" and served none of those three files.
COPY js/ /app/frontend/js/
RUN mkdir -p /app/frontend/gacyber_toolkit \
    && cp -a /app/gacyber_toolkit/. /app/frontend/gacyber_toolkit/ 2>/dev/null || true

RUN mkdir -p /app/data /app/logs /app/backups

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend
ENV DUCKDB_PATH=/app/data/jakal.duckdb
ENV FRONTEND_DIR=/app/frontend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
