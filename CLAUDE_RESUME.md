# CLAUDE RESUME — pick up here (written 2026-10-20)

Local D: `agent hub/Enterprise-Application` is NOT visible from Grok. Source of truth used: GitHub `main`.

## Where main actually is
- Repo: https://github.com/thepeoplesrealty100-ops/Enterprise-Application
- `main` tip when this note was written: `a61dbdac` (2026-10-11) branding/date fix, after a long Sonnet 4.6 visual pass (AtlasMesh, Developer Tools, dashboard, training grid, compliance tiles).
- `index.html` is the operator console (~619 KB). Backend is FastAPI in `backend/`.
- Do **not** restart from `os.html`. That file is an older, smaller copy and is not in the repo.

## Branches that are NOT main
| Branch | Tip | Meaning |
|---|---|---|
| `feat/v4-all` | `2f75dcaf` (2026-09-10) | Older real-functionality pass. **Already absorbed** into later `main` (threat intel, SOAR, assistant, agent exist on main). Do not merge it blindly — it will regress October UI. |
| `claude/enterprise-app-security-review-xialot` | `067544cb` (2026-09-14) | Haiku pass from the v2.10 brief (indexes, /metrics, live fabric renderers, client portal). Also older than current main. Cherry-pick only if a specific function is missing. |
| `master` | `0feb626` | Legacy. Ignore. |

## What Claude already finished (do not redo)
1. Blank-app fix: escaped `</script>` inside the XSS sample string (`93877ff`).
2. AtlasMesh IT-Glue style docs UI + `/api/docs/*` (create, list, view, delete, CSV export, counts).
3. Operator console `/activity`, Developer Tools nav, dashboard KPI tiles, agent activity panel.
4. Real assistant tool-calling: `backend/routers/assistant.py` (`/api/assistant/chat` + `/generate`). Router mode works with no API key. LLM mode uses the Integrations Anthropic key.
5. SOAR auto-triage, threat intel, fleet agent, OSV/NVD scan are on main.
6. **This session:** AtlasMesh pencil button is no longer "coming soon". `atlasEditRecord` loads `GET /api/docs/assets/{id}` and saves with `PUT` (name + field_spec).

## Next work, in order
1. **Client import XLS/XLSX** — `window._parseXlsx` in `index.html` still returns a placeholder row. Add SheetJS from CDN or parse xlsx in Python (`POST /api/docs/import`) and map columns. CSV already works.
2. **atlasSortBy** is an empty function. Sort the loaded table client-side.
3. **Run and fix tests** on the machine that has the venv: `cd backend && python -m pytest tests/ -q`. Do not claim a count without running it.
4. **Local vs GitHub:** on the D: copy run `git fetch origin && git status -sb && git log -1 --oneline`. If it is not `a61dbdac` or later, pull `origin/main` before editing. Push when the Atlas edit + whatever you add is verified in the browser at `http://localhost:8000`.
5. **Do not** rebuild the console as a second app. Keep editing `index.html` + `backend/routers/*`.
6. **Do not** put real exploit payloads or live phishing links in the UI. Training content stays placeholder links.

## How to run (Ubuntu or the D: folder)
```bash
bash setup-jakal-quick.sh
cd backend && python3 -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```
Docker: `docker compose up -d --build` then open port 8000.

## Verify the edit that was just added
AtlasMesh → any asset type with rows → pencil icon → change a field → Save → row refreshes. Delete still works.
