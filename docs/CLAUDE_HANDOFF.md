# JAKAL — Claude handoff (2026-09-27)

## Primary AI model
- **Use Claude (Anthropic) as the primary LLM.** Ollama is offline/dev fallback only.
- Config: `backend/config/__init__.py`
  - `LLM_ENGINE` default = `claude`
  - `CLAUDE_MODEL` default = `claude-sonnet-4-20250514`
  - Requires `CLAUDE_API_KEY` in environment / `.env`
- Health: `GET /api/llm/health` returns engine, model, key status.

## Branch / PR
- Feature branch: `feat/settings-developer-system-profile`
- PR: https://github.com/thepeoplesrealty100-ops/Enterprise-Application/pull/21
- Settings + visual polish: `408d697`. Claude-primary + fleet robustness: apply patch `0004`.

## What is already built (do not rewrite)
| Area | Status |
|------|--------|
| Global Fleet live from `/api/dashboard/fleet` | Working |
| Fabric posture `/api/fabric/status` | Working |
| Agent logs `/api/agent/logs` | Working |
| Response isolate/quarantine/triage (Approval Gate) | Working |
| Settings: Developer / Global System / User Profile | Working |
| IAM sessions + revoke-others | Working |
| Resonance `auto_stage_severity_floor` | Seeded |
| Visual polish v2.11 | Working |
| Human Approval Gate for HIGH actions | Core safety invariant |

## Safety invariants (never break)
1. Isolate / quarantine **host** actions are **staged**, never auto-executed.
2. HIGH/CRITICAL payloads go through Human Approval Gate (+ optional Maya 2FA).
3. PQC audit trail on security-sensitive actions.
4. Claude is primary LLM; do not switch default to Ollama.

## Suggested next work
1. Merge PR #21 after CI green.
2. Device detail: findings from last scan.
3. Fabric 7-pillar scorecard UI (`by_pillar` already in API).
4. Agent activity timeline on Global Dashboard.
5. SOAR playbook designer on existing routers.
6. Loading/error/success states on every table action.
7. Operator Console slash-commands fully live.

## Key files
- UI: `index.html`, `integration.js`, `js/jakal-live-data.js`, `js/operator-console.js`
- LLM: `backend/llm_orchestrator.py`, `backend/config/__init__.py`
- Settings: `backend/routers/settings_dev.py`
- Response: `backend/routers/response.py`
- Fleet: `backend/routers/ui_bridge.py`
- Fabric: `backend/routers/fabric.py`

## Local verify
```powershell
cd C:\Users\Freddy\Enterprise-Application
git checkout feat/settings-developer-system-profile
git pull
# .env: CLAUDE_API_KEY=...  LLM_ENGINE=claude
```
