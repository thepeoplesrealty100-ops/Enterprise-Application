# JAKAL Response Console

React/Vite SPA for the v3.0 compliance-gated containment workflow
(`ResponseConsole`, `ComplianceBadgeGroup`, `AttackPathCanvas`). Talks to the
FastAPI endpoints in `backend/routers/response.py` — see
`docs/API_PHASE3.md` for the contract.

This is a separate surface from the legacy operator UI (`index.html` /
`integration.js` at the repo root, served by `backend/app.py` at `/`); that
UI is untouched by this app.

## Develop

```bash
cd frontend
npm install
npm run dev       # served on :5173, proxies /api to localhost:8000
```

Run the backend separately (`cd backend && uvicorn app:app --reload`) for
the proxy target.

## Build

```bash
npm run build      # outputs frontend/dist
```

`backend/app.py` mounts `frontend/dist` at `/console` automatically when
present — no config needed. Without a build, `/console` simply isn't
mounted and the rest of the app is unaffected.
