# Repository Consolidation & Hardening Report

**Date:** 2026-09-08
**Branch:** `feat/clean-consolidate` (intended to become the single canonical `main`)

## 1. What was wrong

- **Raw GitHub Pages 404 HTML leaking into the UI.** `integration.js`'s `api()`
  stored non-JSON response bodies as `{ raw: text }` and put the full HTML body
  into error messages, which then rendered into panels, the health badge, live
  injects and the console. On a static host (GitHub Pages) every `/api/*` and
  `/health` call returns the "Site not found" 404 page, so that markup was dumped
  verbatim into operator panels.
- **The module auto-booted on import**, bypassing the host guard in `index.html`,
  so it ran (and failed loudly) even on static hosts.
- **Two diverged lineages.** `main` carried the backend hardening; `feat/v4-all`
  (identical to `v3.0-ontology-maya-enterprise`) carried six v4 modules plus a
  large amount of redundant deployment-doc bloat. Neither was a clean superset.
- **`backend-v3/`** was an abandoned parallel Postgres rewrite (the repo's own
  archived plan flagged it "old/unused — delete").
- **Six v4 module files** existed but were **unwired**, and `av_command_center.py`
  crashed on import (`Optional` used but never imported).

## 2. What changed

### Frontend robustness (the 404-dump fix)
- `api()` now inspects `content-type` and the body; any HTML / non-JSON / 404 is
  converted into a **clean, bounded, escaped error** — raw markup can never reach
  the DOM. HTML/404 flips the client into a clean **DEMO MODE**.
- Added `probeBackend()`; `startIntegration()` probes first and renders a clean
  "DEMO MODE — live backend not connected" state instead of failing fetches.
- Removed the unconditional auto-boot; `index.html` owns booting.
- `refreshHealth()` shows a clean demo/offline state, never raw error text.

### Operator Command Console (new)
- A production-grade, collapsible console (input + history with ↑/↓, Run/Clear,
  minimize). Commands: `help, status, health, fabric, fleet, scan <t>,
  quantum, seed, approvals, darkweb, compliance, clear`.
- Live-wires to the REST API when a backend is present; returns clean, clearly
  labelled sample output in demo mode. Output is bounded + escaped — **no raw
  HTML, ever**.

### Backend consolidation
- Ported and **wired** the six v4 modules onto the hardened backend:
  `av_command_center, digital_twin, autonomous_response,
  compliance_intelligence, energy_logic, vr_command_center`
  (+ `services/sensor_trigger_engine.py`, `database_schema_v4.py`).
- Fixed the `Optional` import crash in `av_command_center.py`.
- Route count: **229 → 311**. Full app boots; **all new endpoints return clean JSON**.

### Cleanup
- Removed `backend-v3/` (dead) and its reference in `vault.py`.

## 3. Verification
- Backend boots cleanly (graceful degradation for optional deps).
- **Backend test suite: 74 passed / 0 failed** on the touched areas; full suite green.
- New endpoints verified in-process (11/11 OK, 2 correct 422 validations).
- **Browser QA (Chromium), both modes:** zero leaked 404/HTML dumps; DEMO MODE
  badge clean; LIVE mode shows real health + fabric; console works in both.

## 4. Branch hygiene (to apply on push)
- Delete `master` (23 behind, 0 ahead), `claude/track-a-containment-hardening`
  (merged), `claude/enterprise-app-security-review-xialot` (identical to main).
- Archive-tag then delete `feat/v4-all` + `v3.0-ontology-maya-enterprise` once
  their code is merged here (this branch).
