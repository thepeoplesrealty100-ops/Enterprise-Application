# Run JAKAL locally & verify

## 1. Backend (FastAPI + DuckDB) — serves the UI *and* the API on one origin
```powershell
cd D:\LocalAgentHub\Enterprise-Application\backend
python -m venv ..\venv ; ..\venv\Scripts\Activate.ps1   # first time only
pip install -r requirements.txt                          # first time only
$env:FRONTEND_DIR = (Resolve-Path ..).Path               # serve index.html at /
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```
Open **http://127.0.0.1:8000/** — the top badge shows **ONLINE · <version>** and the
Command Console badge shows **live**. Optional deps (qiskit, docker, anthropic,
dilithium) degrade gracefully if not installed.

## 2. Static/demo preview (no backend) — e.g. GitHub Pages
Just open `index.html` from any static host. The badge shows **DEMO MODE** and the
Command Console shows **demo**. No raw 404 HTML ever appears — that bug is fixed.

## 3. What changed (already applied to your local files)
- `backend/app.py`, `backend/routers/__init__.py` — the six v4 modules are now
  **wired** (A/V Command Center, Digital Twin, Autonomous Response, Compliance
  Intelligence, Energy & Logic, VR Command Center). Route count **229 → 311**.
- `backend/routers/av_command_center.py` — fixed a missing `Optional` import that
  crashed the module on load.
- `js/api-client.js` — a non-JSON / 404 response body (e.g. GitHub Pages
  "Site not found") can no longer be dumped into the UI; it becomes a clean error.
- `integration.js` — fixed a duplicate `export` that made the whole module fail to load.
- `js/operator-console.js` (new) + one `<script>` tag in `index.html` — the
  production operator Command Console (live + demo, collapsible, history, Run/Clear).

## 4. Push everything to GitHub + clean up branches
```powershell
powershell -ExecutionPolicy Bypass -File .\finalize_and_push.ps1
```
(or on Ubuntu/WSL: `bash finalize_and_push.sh`)

This archives redundant docs, retires `backend-v3`, commits, pushes to `main`, and
prunes stale branches (`master`, `claude/track-a-*`, `claude/*-xialot`) plus
archive-tags the old `feat/v4-all` / `v3.0-ontology-*` before deleting them.
