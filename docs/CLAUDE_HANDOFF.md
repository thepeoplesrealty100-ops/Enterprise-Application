# JAKAL — Claude handoff (2026-09-27 final Grok session)

## Mission
Harden JAKAL Enterprise-Application. **Do not rewrite.** Surgical work on FastAPI + index.html only.

## Primary AI
- **Claude** primary (`LLM_ENGINE=claude`, `CLAUDE_MODEL=claude-sonnet-4-20250514`)
- Ollama = offline fallback only
- `.env`: `CLAUDE_API_KEY=...`
- `GET /api/llm/health` · Operator free-text → `/api/assistant/generate`

## Branch / PR
- `feat/settings-developer-system-profile`
- PR: https://github.com/thepeoplesrealty100-ops/Enterprise-Application/pull/21
- **Apply patch `0007-feat-full-live-inject-toast-timeline-soar.patch`** after pull if UI features missing.

## Safety (never break)
1. Host isolate/quarantine **staged only**
2. HIGH/CRITICAL → Approval Gate
3. PQC audit trail
4. Claude stays default LLM

## Completeness matrix
| Module | Live backend | UI robust |
|--------|--------------|-----------|
| Global Dashboard / Fleet | yes | toast + device actions + timeline |
| Fabric (7 capabilities) | yes | pillar bars + live inject |
| SOAR | yes | loading/finally + live tickets panel |
| Vulnerabilities | yes | scan progress + live CVE panel |
| Integrations | yes | live status panel |
| Audit Trail | yes | live IAM audit panel |
| Settings Dev/System/Profile | yes | wired |
| Response / Awareness / Dark Web | yes | integration inject |
| Resonance / Q'AIP / Energy / Ontology / Quantum | yes | widgets |
| Operator Console | yes | /llm /timeline / Claude free-text |

## What Grok shipped (0007)
- `jakalToast` + CSS
- Fleet Scan/Isolate/Quarantine → APIs
- Fabric pillar progress bars
- SOAR run loading/finally + toasts
- Agent activity timeline on dashboard
- injectPageLive: soar, vulns, integrations, audit, fabric subs
- Operator Console Claude path + /llm + /timeline
- Claude system prompt + llm health endpoint

## Next for Claude
1. Merge PR #21 (CI green)
2. Fabric capability card drill-down metrics
3. Ensure every destructive button uses jakalToast
4. Backend CI full suite on branch
5. Any remaining demo paths in Operator Console

## Verify (PowerShell)
```powershell
cd C:\Users\Freddy\Enterprise-Application
git pull origin feat/settings-developer-system-profile
git am path\to\0007-feat-full-live-inject-toast-timeline-soar.patch
git push origin feat/settings-developer-system-profile
# .env CLAUDE_API_KEY=... then restart backend, Ctrl+Shift+R
```
