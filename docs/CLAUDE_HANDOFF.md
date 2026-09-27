# JAKAL — Claude handoff (updated 2026-09-27)

## Mission
Build and harden the JAKAL Enterprise-Application (Horizon / JAKALHUS-OS Console): a 24-module cybersecurity + agentic AI platform. **Do not rewrite the app.** Extend the existing FastAPI + index.html foundation surgically.

## Primary AI model (mandatory)
- **Claude (Anthropic) is the primary LLM.** Ollama is offline/dev fallback only.
- `LLM_ENGINE=claude` (default in `backend/config/__init__.py`)
- `CLAUDE_MODEL=claude-sonnet-4-20250514`
- Requires `CLAUDE_API_KEY` in `.env` (production hard-fails without it; development warns)
- Health: `GET /api/llm/health`
- Orchestrator: `backend/llm_orchestrator.py` (system prompt = security ops + approval-gate bias)

## Branch / PR
- Branch: `feat/settings-developer-system-profile`
- PR: https://github.com/thepeoplesrealty100-ops/Enterprise-Application/pull/21
- Merge into `main` when CI is green.
- Apply local patch `0005-feat-fabric-fleet-soar-claude-handoff.patch` if index.html device actions / fabric bars are missing after pull.

## Safety invariants (never break)
1. Host **isolate / quarantine** are **staged** via Human Approval Gate — never auto-execute against production.
2. HIGH/CRITICAL payloads require approval (+ optional Maya 2FA).
3. PQC audit trail on security-sensitive actions.
4. Claude remains default LLM; do not flip default to Ollama.

## What is live / robust
| Module / area | Backend | UI | Notes |
|---------------|---------|-----|--------|
| Global Dashboard + Fleet | `/api/dashboard/fleet` | Live cards + detail actions | Scan/Isolate/Quarantine |
| Fabric Zero Trust posture | `/api/fabric/status` | Pillar bars + capability cards | NSA/CISA maturity |
| SOAR | `/api/soar/auto-triage`, tickets | Run + ticket list + loading state | Containment approval-gated |
| Response | `/api/response/*` | Live Ops + fleet actions | Triage, IOC, isolate |
| Settings Developer / System / User Profile | `/api/settings/developer`, IAM sessions | Global Settings tabs | This branch |
| Resonance / Q'AIP / Energy | routers present | Module pages | |
| Compliance / Dark Web / Awareness | routers present | Module pages | |
| Cheatsheet / Integrations / Audit | routers present | Module pages | |
| Quantum / Ontology / Canvas | routers present | Module pages | |
| Operator Console | `/health`, fabric | Slash commands | |
| Live data bridge | — | `js/jakal-live-data.js` | Fleet ids, fabric, agent logs |

## Key files
- UI: `index.html`, `integration.js`, `js/jakal-live-data.js`, `js/operator-console.js`
- Config/LLM: `backend/config/__init__.py`, `backend/llm_orchestrator.py`, `.env.example`
- Settings: `backend/routers/settings_dev.py`
- Response / SOAR: `backend/routers/response.py`, `backend/routers/soar.py`
- Fleet bridge: `backend/routers/ui_bridge.py`
- Fabric: `backend/routers/fabric.py`

## Suggested next work (priority)
1. Merge PR #21; pull main.
2. Ensure `.env` has `CLAUDE_API_KEY` on operator machines.
3. Agent activity **timeline** visualization on Global Dashboard (`/api/agent/logs`).
4. Per-capability drill-down actions on Fabric cards.
5. SOAR playbook library catalog UI beyond auto-triage.
6. Uniform loading/error/success toasts on every destructive table action.
7. Operator Console: replace remaining demo branches with live endpoints.
8. Keep `backend/tests/test_settings_developer.py` green in CI.

## Local verify (Windows PowerShell)
```powershell
cd C:\Users\Freddy\Enterprise-Application
git checkout feat/settings-developer-system-profile
git pull origin feat/settings-developer-system-profile
# Edit .env: CLAUDE_API_KEY=sk-ant-...
# Restart backend, Ctrl+Shift+R on http://localhost:8000
```

## Research themes already applied
Palantir Workshop hierarchy, Anduril single-pane status, IBM QRadar dark SOC density,
NSA/CISA Zero Trust pillars, Claude-first agentic security ops.
