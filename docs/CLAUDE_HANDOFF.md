# JAKAL — Claude handoff (2026-09-27)

## Why the local app "doesn't do much" / AIP errors
Running process shows **`llm_engine: ollama`**. Ollama has no model (`llama3` 404).
Repo default is **Claude**. Fix:

```
LLM_ENGINE=claude
CLAUDE_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-20250514
```
Restart backend. Confirm `GET /health` shows `llm_engine: claude`.

## Offline safety net (patch 0008)
`services/llm_client.py`:
1. Prefers Claude key from env or Integrations vault
2. Ollama only as fallback
3. Deterministic offline analysis for AIP Investigator so canvas still adds next-step nodes

Apply: `0008-fix-llm-offline-aip-investigator.patch`

## What works live today
- Health, DuckDB, fabric 67.9 Advanced, 7 caps
- Live Ops: reports, agent logs, SSE
- Full module nav + SOAR/response/fleet APIs

## Branch
`feat/settings-developer-system-profile` · PR #21

## Safety
Isolate/quarantine staged only. Claude primary. Do not rewrite the app.
