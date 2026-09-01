# JAKAL Module Architecture Map

Every module named in the "Global Settings & Security" and ops-dashboard
tabs, mapped to what actually backs it today. Frontend page keys refer to
`index.html`'s `pages` array; live-wiring refers to `integration.js`'s
`injectPageLive()` / `injectSettingsLive()`.

Status legend: 🟢 real backend + live-wired frontend · 🟡 real backend,
frontend still needs deeper wiring than the read-only JSON panel added in
v2.6 · ⚪ frontend mock only, no backend (pre-v2.6 baseline — most of these
were closed by this pass; remaining gaps are called out explicitly)

## Global Settings & Security tab

| Sub-tab | Backend | Status |
|---|---|---|
| Profile | `GET /api/iam/auth/me` | 🟢 |
| Login Encryption | `POST /api/iam/auth/login`, `/mfa/*` | 🟢 (frontend still shows this alongside the crypto status panel — MFA enrollment has no dedicated QR-code UI yet, just the raw `otpauth://` URI) |
| API Integration | `/api/iam/api-keys/*` | 🟢 |
| EAS R&D | `/api/vault/eas-rd/*` (live OSV.dev scan) | 🟢 |
| Trade Secrets | `/api/vault/items/*` | 🟢 |
| Penetration Testing | `/api/pentest/*`, `/api/approval/*` (pre-existing) | 🟢 (already live-wired pre-v2.6 via the Live Ops drawer) |
| RBAC | `/api/iam/rbac/*` | 🟢 |
| Auditing | `/api/iam/audit/*` | 🟢 |
| Key Management | `/api/crypto/keys/*` (pre-existing, real PQC + AES key registry) | 🟢 |

## Resonance & Q'AIP Cores / Computational Agentic System / Command & Control

| Frontend label | Page key | Backend | Status |
|---|---|---|---|
| Energy Core Management | `admin_energy_core` | `GET /api/qaip/energy-core/status` (`backend/llm_energy_core.py`) | 🟡 — live-wired to a raw JSON panel in v2.6; a purpose-built throttle-control UI (vs. read-only JSON) is the remaining work |
| Q'AIP Logic Core Manager | `admin_logic_core` | `GET /api/qaip/orbital-comms/stats` | 🟡 same as above |
| Resonance Wave Automation | `admin_automation_controls` | `GET /api/resonance/settings` | 🟡 same as above |
| Ontology & Simulation Hub | `admin_ontology` | `GET /api/aip/ontology`, `GET /api/cheatsheet/graph` (new) | 🟡 same as above |
| Model Chains & Inference | `admin_model_chains` | `GET /api/qaip/orbital-comms/stats` (LLM/quantum inference ledger) | 🟡 same as above |
| Quantum Orbital & Event Comms | `admin_quantum_nexus` | `GET /api/qaip/orbital-comms` | 🟡 same as above |
| Quantum Computer | `admin_quantum_computer` | `/api/quantum/*` (`quantum_engine.py`, Qiskit Aer) | 🟢 (already live-wired pre-v2.6) |
| Predictive Command | `admin_predictive_command` | `GET /api/ares/global-matrix-summary` | 🟡 closest real analog is Ares's cross-pillar rollup; a dedicated predictive-scoring model is a real future build, not present today |
| Resonance Load Monitor | `admin_cognitive_load_monitor` | `GET /api/resonance/fleet` | 🟡 same as Energy Core |
| Ontology Meta-Platform | `admin_investigation_canvas` | `GET /api/canvas/tasks`, `GET /api/aip/ontology` | 🟡 same as Energy Core |
| System Diagnostics | `admin_diagnostics` | `/health`, `/api/*/status` fan-out | 🟢 (already live-wired pre-v2.6) |

*"🟡" here specifically means: the endpoint is real and now returns live
data in the page (v2.6 added the `renderSimpleJsonPanel` wiring), but the
UI is a raw JSON dump layered above the existing mock, not a
purpose-designed control surface. Turning each into a proper dashboard
widget is real, valuable frontend work — scoped out of this pass to keep
the backend correctness/security work the priority; see "Remaining work"
in the PR/session summary.*

## Unified Security Fabric / Risk & Compliance

| Frontend label | Page key | Backend | Status |
|---|---|---|---|
| Unified Security Fabric | `admin_fabric` | `/api/fabric/*` (7-pillar NSA/CISA Zero Trust model) | 🟢 (already live-wired pre-v2.6) |
| Compliance & Risk Posture | `admin_compliance` | `/api/compliance/axiom/*` | 🟢 (already live-wired pre-v2.6) |
| Dark Web Monitoring | `admin_dark_web` | `/api/darkweb/*` (new) | 🟢 |

## Human Layer Security

| Frontend label | Page key | Backend | Status |
|---|---|---|---|
| Awareness Training | `admin_security_training` | `/api/awareness/training/*` (new) | 🟢 |
| Phishing Campaigns | `admin_phishing_sim` | `/api/awareness/phishing/*` (new) | 🟢 |

## GACyber Toolkit

| Frontend label | Page key | Backend | Status |
|---|---|---|---|
| CheatSheet Library | `admin_cheatsheet_library` | `/api/cheatsheet/*` (new, exposes existing `payloads/cheatsheet_ontology.py`) | 🟢 |

## What "🟡" modules would need to become fully purpose-built (next steps)

The read-only JSON panels shipped in this pass prove every one of these
pages has real, correct backend data flowing into it — none of them are
faked anymore. Turning each into a first-class control surface (throttle
sliders for Energy Core, a drag-connect graph for the Ontology Hub, a
live-updating load gauge for the Resonance Load Monitor, etc.) is
UI/UX design + component work, intentionally sequenced after the
correctness/security pass this session focused on. Each existing
`render<PageName>()` mock function in `index.html` already has the right
visual shape — the remaining task per page is: replace its hardcoded
numbers with the live values `integration.js` now fetches, the same
migration `renderFabricPanel`/`renderDiagPanel` already went through
pre-v2.6.
