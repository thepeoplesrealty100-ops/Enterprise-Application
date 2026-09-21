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

## 3. Push changes to GitHub
```bash
git add -A
git commit -m "your message here"
git push origin main
```
Standard git — nothing else required. (An earlier version of this doc pointed at
`finalize_and_push.ps1`/`.sh`, one-time scripts from a specific past consolidation
that also pruned branches and force-pushed `main`. Their job is done; they've been
removed so nobody runs that branch-pruning step again by accident against branches
that still matter.)
