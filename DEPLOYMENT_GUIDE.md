# JAKAL Deployment Guide

Replaces `PRODUCTION_DEPLOYMENT_GUIDE.md` and `KUBERNETES_DEPLOYMENT_AND_CLAUDE_GUIDE.md`,
which had drifted out of sync with the actual codebase (wrong Dockerfile paths, an invalid
`docker run --port` flag, a `DATABASE_PATH` env var that doesn't exist, a documented
`/api/claude/ask` endpoint that was never built, and version labels three releases stale).
Everything below was checked against the current repo, not carried over from either doc.

## Table of Contents
1. [Docker (primary path)](#docker-primary-path)
2. [Environment Variables](#environment-variables)
3. [Kubernetes](#kubernetes)
4. [Health Checks & Verification](#health-checks--verification)
5. [Monitoring (optional, not currently wired in)](#monitoring-optional-not-currently-wired-in)
6. [Troubleshooting](#troubleshooting)

---

## Docker (primary path)

This is the only deployment path actually exercised in this repo's own tooling.

```bash
# From the repo root
docker compose up -d --build
```

That's it — `docker-compose.yml` builds from the root `Dockerfile`, bind-mounts `./data`,
`./logs`, `./backups`, `./gacyber_toolkit` (read-only), and the frontend files
(`index.html`, `integration.js`, `world_land_map.json`), and exposes port 8000.

**Manual build/run**, if you need it outside compose:
```bash
docker build -t jakal-backend -f Dockerfile .
docker run -d --name jakal-backend -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -e JAKAL_MASTER_KEY=your-key-here \
  jakal-backend
```
(`--port` is not a real Docker flag — it's `-p`/`--publish`. The old guide had this wrong.)

**Image**: single-stage, `python:3.11-slim` base. No multi-stage Node/Vite build — the
operator UI is plain HTML/JS, not a bundled frontend project.

## Environment Variables

The authoritative template is **`backend/.env.example`**, not the one at the repo root
(that one describes a Supabase/Firebase/Oracle/Vercel stack that was never built and has
been removed). Copy it to `backend/.env` and fill in what you need — `setup-jakal-quick.sh`/
`.ps1` do this for you automatically.

| Variable | Purpose |
|---|---|
| `DUCKDB_PATH` | Database file location (default `/app/data/jakal.duckdb` in the container) |
| `JAKAL_MASTER_KEY` | KEK for encrypted keys in `encryption_keys`. **Unset = ephemeral** — session keys become unrecoverable after restart. Set this for any real deployment. |
| `LLM_ENGINE` | `ollama` (default) or `claude` |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Only used when `LLM_ENGINE=ollama` |
| `ANTHROPIC_API_KEY` / `CLAUDE_MODEL` | Only used when `LLM_ENGINE=claude` |
| `IBM_QUANTUM_TOKEN` / `IBM_QUANTUM_CHANNEL` / `IBM_BACKEND_NAME` | Optional — routes quantum jobs to real IBM hardware instead of the local Aer simulator |
| `HIBP_API_KEY` | Optional — enables the real Have I Been Pwned connector for Dark Web Monitoring |
| `EDR_WEBHOOK_URL` / `EDR_WEBHOOK_SECRET` | Optional — HMAC-signed webhook target for external EDR/firewall/SOAR containment actions |
| `PQC_PROFILE` | `commercial` (default, ML-DSA-65) or `cnsa2` (ML-DSA-87) |
| `CORS_ORIGINS` | Comma-separated allowed origins |

## Kubernetes

Two manifests exist in `k8s/`, and they are **not equivalent** — pick deliberately, don't
apply whichever one is closer to the top of a search result:

- **`jakal-backend-complete.yaml`** — the more complete one. Deployment, Service, a real
  `PersistentVolumeClaim`, ConfigMap, ServiceAccount/RBAC, HorizontalPodAutoscaler,
  PodDisruptionBudget. Use this one.
- **`jakal-deployment.yaml`** — simpler, but its data volume is `emptyDir: {}`, meaning
  **the DuckDB database is lost on every pod restart or reschedule**. Fine for a quick
  smoke test, wrong for anything you want to keep data in.

**Before applying either**: both manifests reference placeholder image tags
(`jakal:2.8`, `jakal:2.0`) that don't match anything this repo actually builds. Build and
push your own image first, then update the `image:` field:

```bash
docker build -t your-registry/jakal-backend:latest -f Dockerfile .
docker push your-registry/jakal-backend:latest
# then edit the image: line in k8s/jakal-backend-complete.yaml to match
kubectl apply -f k8s/jakal-backend-complete.yaml
```

Neither manifest has been applied against a real cluster as part of writing this guide —
treat them as a solid starting point, not a tested deployment path.

## Health Checks & Verification

```bash
curl http://localhost:8000/health              # basic liveness
curl http://localhost:8000/api/health/detailed  # DB status, resource usage, feature flags
```

API reference (Swagger UI, auto-generated from the actual mounted routes): `/docs` —
not `/api/docs`, which the old K8s guide had wrong.

There are 45 routers mounted (`grep -c include_router backend/app.py` if you want to
verify against a specific commit) — not the "13 UI Bridge endpoints" the old production
guide referenced, which predates most of this codebase.

## Monitoring (optional, not currently wired in)

`nginx.conf` and `prometheus.yml` exist in the repo root but are **not** referenced by
the active `docker-compose.yml` — they're example configs for a reverse-proxy +
Prometheus/Grafana stack you'd need to wire in yourself if you want it. Nothing in this
repo runs them by default, and no scrape target or reverse-proxy container currently
exists. If you want real monitoring, that's genuine follow-up work, not a flag you flip.

## Troubleshooting

**`docker compose up --build` fails on a "Dockerfile not found" or Vite/npm error** —
you're likely on an old checkout. Both of those were real bugs (compose referencing a
file that didn't exist, and a broken Node build stage for a frontend that was never
finished) — fixed as of the commit that introduced this guide.

**Frontend loads but nothing renders / no navigation works** — check the browser console
for CSP violations. `backend/middleware/security_hardening.py`'s Content-Security-Policy
allowlist must include every CDN host `index.html` actually loads (Tailwind, Lucide,
Chart.js, Three.js, D3, Google Fonts) — if you add a new library to `index.html`, add its
host to the CSP too, or the browser will silently drop the script with no error in the
Network tab, only in Console.

**`JAKAL_MASTER_KEY not set` warning in logs** — expected if you haven't set it. Fine for
local testing; set a real value before anything you intend to keep running.
