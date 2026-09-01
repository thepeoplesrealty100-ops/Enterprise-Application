# JAKAL Module Architecture Map

Every module named in the "Global Settings & Security" and ops-dashboard
tabs, mapped to what actually backs it today. Frontend page keys refer to
`index.html`'s `pages` array; live-wiring refers to `integration.js`'s
`injectPageLive()` / `injectSettingsLive()`.

Status legend: 🟢 real backend + a purpose-built live widget · 🟡 real
backend, live-wired, but the widget is still a generic read-only display
rather than a full control surface · ⚪ frontend mock only, no backend
(pre-v2.6 baseline — closed for every module below as of v2.7)

## Global Settings & Security tab

| Sub-tab | Backend | Status |
|---|---|---|
| Profile | `GET /api/iam/auth/me` | 🟢 |
| Login Encryption | `POST /api/iam/auth/login`, `/mfa/*` | 🟢 (v2.7: real server-rendered QR code for MFA enrollment, not just a raw `otpauth://` string) |
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
| Energy Core Management | `admin_energy_core` | `GET /api/qaip/energy-core/status` | 🟢 (v2.7: throttle gauge widget) |
| Q'AIP Logic Core Manager | `admin_logic_core` | `GET /api/qaip/orbital-comms/stats` | 🟢 (v2.7: inference ledger table) |
| Resonance Wave Automation | `admin_automation_controls` | `GET/POST /api/resonance/automation-settings/*` (v2.8) + `/api/resonance/policies/*`, `/api/resonance/enforce/*`, `/api/resonance/audit*` (v2.9, merged from a parallel build) | 🟢 (real, write-controlled automation knobs each read by a real enforcement point, PLUS named isolation policies with a staged/audited enforce workflow (simulate → request approval → execute → release) backed by a real, tamper-evident hash-chained audit trail and the same real Docker/webhook enforcement connectors response.py uses — see docs/v2.8-automation-policy-and-enforcement.md and docs/v2.9-batch1-reconciliation.md) |
| Ontology & Simulation Hub | `admin_ontology` | `GET /api/cheatsheet/graph` | 🟢 (v2.7: category/phase relationship chip graph) |
| Model Chains & Inference | `admin_model_chains` | `GET /api/qaip/orbital-comms/stats` | 🟢 (v2.7: inference ledger table) |
| Quantum Orbital & Event Comms | `admin_quantum_nexus` | `GET /api/qaip/orbital-comms` | 🟢 (v2.7: event stream feed) |
| Quantum Computer | `admin_quantum_computer` | `/api/quantum/*` (Qiskit Aer) | 🟢 (already live-wired pre-v2.6) |
| Predictive Command | `admin_predictive_command` | `GET /api/ares/global-matrix-summary` | 🟢 (v2.7: rollup stat cards). Closest real analog to "predictive" is Ares's cross-pillar rollup — a dedicated forecasting model is still a real future build, not present today |
| Resonance Load Monitor | `admin_cognitive_load_monitor` | `GET /api/resonance/fleet` | 🟢 (v2.7: fleet load gauge + per-host list) |
| Ontology Meta-Platform | `admin_investigation_canvas` | `GET /api/canvas/tasks` | 🟢 (v2.7: pending/in-progress/completed kanban board) |
| System Diagnostics | `admin_diagnostics` | `/health`, `/api/*/status` fan-out | 🟢 (already live-wired pre-v2.6) |

## Unified Security Fabric / Risk & Compliance

| Frontend label | Page key | Backend | Status |
|---|---|---|---|
| Unified Security Fabric | `admin_fabric` | `/api/fabric/*` (7-pillar NSA/CISA Zero Trust model) | 🟢 (already live-wired pre-v2.6) |
| Compliance & Risk Posture | `admin_compliance` | `/api/compliance/axiom/*` | 🟢 (already live-wired pre-v2.6) |
| Dark Web Monitoring | `admin_dark_web` | `/api/darkweb/*` | 🟢 (v2.7: connector-status badge + setup link, real HIBP wiring) |

## Human Layer Security

| Frontend label | Page key | Backend | Status |
|---|---|---|---|
| Awareness Training | `admin_security_training` | `/api/awareness/training/*` | 🟢 |
| Phishing Campaigns | `admin_phishing_sim` | `/api/awareness/phishing/*` | 🟢 |

## GACyber Toolkit

| Frontend label | Page key | Backend | Status |
|---|---|---|---|
| CheatSheet Library | `admin_cheatsheet_library` | `/api/cheatsheet/*` — ontology (13 modules/43 doc-derived tool sheets) **+ v2.7's 43-script real, runnable catalog** with stage → approve → sandbox-execute, plus `/api/scripts/*` (v2.9, merged from a parallel build) — a separate, operator-uploaded script marketplace with catalog approval + sandbox execution + SSE-streamed run output, complementary to the auto-indexed gacyber_toolkit corpus above | 🟢 |

## New in v2.7 — Detection & Response

Not a frontend-mock-to-real migration (there was no prior mock for this) —
genuinely new capability, exposed via the Live Ops drawer's new "Response"
and "Scripts" tabs so it's reachable from any page, not just one settings
tab, per the brief that these should be "actioned from that module or any
module."

| Capability | Backend | Notes |
|---|---|---|
| Triage (score + recommend playbook) | `POST /api/response/triage` | Deterministic `threat_scoring.py` + keyword match against the real playbook catalog; auto-stages containment above severity 0.8 |
| IOC blocking | `POST /api/response/ioc/block` | Real, immediate — writes to `threat_intel` |
| Artifact quarantine | `POST /api/response/quarantine` (artifact) | Real, immediate, data-layer |
| Host quarantine / isolation | `POST /api/response/quarantine` (host), `POST /api/response/isolate-host` | Always staged via the Human Approval Gate — never auto-executed against real infrastructure |
| 14 IR playbooks (was 6) | `security_agents/edr_mdr.py` | +8 in v2.7: supply chain, cloud account compromise, DDoS, insider threat, IoT/OT, emergency patch, wireless rogue AP, PQC crypto-agility |
| Script catalog | `payloads/script_catalog.py`, `/api/cheatsheet/scripts/*` | 43 real scripts from `gacyber_toolkit/`, staged + approval-gated + sandbox-only execution |

## v2.8 — Resonance Wave Automation write control + real containment enforcement

Both gaps called out at the end of v2.7 are closed:

- **Resonance Wave Automation** now has real write control via
  `resonance_policy` (a genuinely new table, deliberately NOT a patch to
  the derived `global_security_settings` snapshot — see
  docs/v2.8-automation-policy-and-enforcement.md for why). Each policy
  knob is read by a real enforcement point: the Detection & Response
  triage threshold, the Trade Secrets vault's role-isolation requirement,
  and the script catalog's auto-approval behavior for LOW-risk scripts.
- **Host isolation/quarantine** now has a real enforcement path:
  `POST /api/response/actions/{id}/enforce`, callable only after human
  approval. A JAKAL-owned sandbox container is genuinely isolated via a
  real Docker network disconnect; an external target is delivered via a
  signed (HMAC-SHA256, replay-protected) webhook to whichever real
  EDR/firewall/SOAR integration the operator configures
  (`EDR_WEBHOOK_URL`) — the same integration shape production tools like
  Cortex XSOAR and Splunk SOAR already use to bridge to CrowdStrike/
  SentinelOne.

Every module named in the original ops-dashboard request is now 🟢.
