# JAKAL — Claude handoff (updated 2026-09-27 ~03:40 EDT)

## Mission
Harden JAKAL Enterprise-Application (Horizon / JAKALHUS-OS Console). **Do not rewrite.** Surgical extensions only on FastAPI + `index.html` foundation.

## Primary AI (mandatory)
- **Claude** is primary. Ollama = offline/dev fallback only.
- `LLM_ENGINE=claude`, `CLAUDE_MODEL=claude-sonnet-4-20250514`, `CLAUDE_API_KEY` in `.env`
- Prod: missing key = hard fail. Dev: soft warn (API still boots).
- `GET /api/llm/health` · orchestrator system prompt = security ops + approval-gate bias
- Operator Console free-text routes to `/api/assistant/generate` (Claude)

## Branch / PR
- `feat/settings-developer-system-profile`
- PR: https://github.com/thepeoplesrealty100-ops/Enterprise-Application/pull/21
- Apply patch **`0006-feat-toast-timeline-operator-claude.patch`** if local is behind (index/integration/operator-console/llm).

## Safety invariants
1. Host isolate/quarantine **staged only** (Approval Gate).
2. HIGH/CRITICAL need human approval (+ optional Maya 2FA).
3. PQC audit on sensitive actions.
4. Never default LLM to Ollama.

## Live / robust matrix
| Area | Notes |
|------|--------|
| Global Fleet | Live `/api/dashboard/fleet`; Scan/Isolate/Quarantine actions |
| Fabric | Pillar progress bars; capability cards; live `/api/fabric/status` |
| SOAR | Auto-triage + tickets + loading/finally + toasts |
| Dashboard activity | Timeline UI (`jakal-timeline`) from agent logs |
| Toasts | `window.jakalToast(msg, 'ok'|'err'|'info')` |
| Operator Console | `/llm`, `/timeline`, free-text → assistant/Claude |
| Settings | Developer / Global System / User Profile |
| Live bridge | `js/jakal-live-data.js` preserves backendIds |

## Key files
`index.html`, `integration.js`, `js/jakal-live-data.js`, `js/operator-console.js`,
`backend/config/__init__.py`, `backend/llm_orchestrator.py`, `backend/app.py`,
`backend/routers/settings_dev.py`, `response.py`, `soar.py`, `ui_bridge.py`, `fabric.py`

## Next priorities for Claude
1. Merge PR #21 when CI green.
2. Fabric capability card drill-down (live metrics per module_key).
3. Uniform toast on every remaining destructive table action.
4. Vuln management pills: ensure live `/api/vulnerability*` bind.
5. Predictive Command / Load Monitor: confirm live widgets in integration inject.
6. Expand SOAR beyond auto-triage if playbook catalog API is added.
7. Keep tests green (`test_settings_developer.py`, suite).

## Local (PowerShell)
```powershell
cd C:\Users\Freddy\Enterprise-Application
git checkout feat/settings-developer-system-profile
git pull origin feat/settings-developer-system-profile
# .env: CLAUDE_API_KEY=... LLM_ENGINE=claude
# Restart backend; Ctrl+Shift+R
```
