Hi everyone,

I've worked with computers and software applications for some time. I won't claim to know coding or anything real technical but what I do know is a good operation and process for a system to run. I know there are alot of things that go behind it but this is just an idea I had.
Anyways, if you want to help or add on or contribute, please feel free. This is just an idea that I had. I'm not prideful or boastful about it so I'm open to constructive feedback. 

Cheers!

---

## Quick start

Pick whichever matches your machine — all three set up the same backend (Python venv, dependencies, `backend/.env`).

**Ubuntu / Linux / WSL (bash):**
```bash
bash setup-jakal-quick.sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File setup-jakal-quick.ps1
```

**Docker:**
```bash
docker compose up -d --build
```

After setup, add your Claude API key to `backend/.env` (never commit this file — it's already in `.gitignore`), then:
```bash
cd backend && python3 -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```
Visit `http://localhost:8000/docs` for the live API reference, or run `python3 seed_demo_data.py` from `backend/` first if you want the platform pre-populated with a realistic sample engagement (scope, findings, MITRE mappings, a pending approval request, etc.) to explore immediately.

## What's in here (v2.3)

- **Post-quantum crypto** — ML-DSA-65 (Dilithium3) signs every agent action and audit-log entry (`backend/crypto/`).
- **Quantum computing** — Qiskit-Aer-backed entropy, Bell-state, and Grover circuits (`backend/quantum_engine.py`).
- **AIP-style payload intelligence** — an ontology-bounded generator that interweaves pre-populated MITRE ATT&CK payloads with the CheatSheet library, across 8 phases including a dedicated **wireless (802.11)** phase (`backend/payloads/`).
- **Unified Security Fabric** — 7 security capabilities (MDR, Zero Trust, SASE, PAM, DNS filtering, email security, DLP) mapped to the NSA/CISA Zero Trust Maturity Model, in one module (`backend/security_agents/unified_fabric.py`).
- **Human Approval Gate** — every HIGH/CRITICAL-risk payload is staged and PQC-signed, then held until a human operator approves or denies it — enforced against the database, not just a flag (`backend/security_agents/exploit_agent.py`).
- **Authorization gate** — scope + insurance + PQC-signed compliance checkpoints in front of every network-facing action (`backend/tools/authorization.py`).
- 25-table DuckDB schema, versioned in `backend/database.py`'s module docstring.

See `backend/tests/` for the test suite (`python -m pytest tests/ -q` from `backend/`).

## What's new in v2.6 — Global Settings & Security

Real backend + live-wired frontend for the tabs that were previously either
missing entirely or hardcoded frontend mock data:

- **IAM** — registration/login, bcrypt password hashing, account lockout,
  TOTP MFA, JWT sessions, RBAC (roles/permissions), API key issuance, and a
  structured, exportable audit log. See `backend/routers/iam.py`.
- **Vault** — a real AES-256-GCM encrypted document vault for Trade
  Secrets, and a live OSV.dev dependency-vulnerability scanner for EAS R&D.
  See `backend/routers/vault.py`.
- **Dark Web Monitoring** — a real Have I Been Pwned connector (needs
  `HIBP_API_KEY`) plus a pluggable interface for paid feeds. See
  `backend/routers/darkweb.py`.
- **Awareness Training + Phishing Campaigns** — real completion tracking
  and campaign click-through stats. See `backend/routers/awareness.py`.
- **CheatSheet Library API** — exposes the existing cheatsheet ontology +
  playbook library that had no API surface before. See
  `backend/routers/cheatsheet.py`.

Full endpoint reference: `docs/v2.6-global-settings-security-api.md`.
Every module name in the ops dashboard mapped to its backing code:
`docs/module-architecture-map.md`. Bugs found and fixed while getting the
test suite from 53/16/6 (pass/fail/error) to 85/0/0:
`docs/v2.6-fixes-and-test-report.md`.

## What's new in v2.7 — Detection & Response + a real script library

- **Detection & Response** (`backend/routers/response.py`) — real,
  immediate IOC blocking + artifact quarantine, and approval-gated
  host isolation/quarantine (never auto-executed against real
  infrastructure). Grounded in NIST SP 800-61 Rev. 3 (CSF 2.0 mapping)
  and MITRE D3FEND defensive-technique IDs.
- **8 new incident-response playbooks** (14 total) — supply chain
  compromise, cloud account compromise, DDoS, insider threat, IoT/OT
  device compromise, emergency vulnerability patch, wireless rogue AP,
  and a PQC crypto-agility incident playbook grounded in NIST IR 8547's
  real 2030/2035 algorithm-deprecation timeline.
- **A real, runnable script catalog** — the 43 `.py`/`.sh`/`.pl`/`.rb`
  scripts already in `gacyber_toolkit/` are now indexed, browsable, and
  actionable: stage → human approval → execute only inside an
  operator-owned sandbox container (never the host, never a live target
  directly).
- **MFA QR codes** — `/api/iam/auth/mfa/enroll` now returns a real
  server-rendered SVG QR code, not just a raw `otpauth://` string.
- **Purpose-built widgets** for every ops-dashboard page that previously
  showed a raw JSON panel (Energy Core, Q'AIP Logic Core, Resonance
  Automation, Ontology Hub, Model Chains, Quantum Nexus, Predictive
  Command, Load Monitor, Investigation Canvas).

Full writeup + research citations: `docs/v2.7-detection-response-and-scripts.md`.

## What's new in v2.8 — Automation policy + real containment enforcement

- **Resonance Wave Automation now has real write control** — `resonance_policy`
  holds knobs (auto-stage severity threshold, vault role-isolation
  enforcement, script auto-approval, sandbox lifetime) that real
  enforcement points actually read, RBAC-gated and PQC-signed on every
  change. Deliberately not a patch to the derived `global_security_settings`
  snapshot — see the doc below for why.
- **Host isolation/quarantine now has a real enforcement path** —
  `POST /api/response/actions/{id}/enforce`: a JAKAL-owned sandbox is
  genuinely isolated via a real Docker network disconnect; an external
  target is delivered via a signed HMAC-SHA256 webhook to your own
  EDR/firewall/SOAR integration (`EDR_WEBHOOK_URL`).

Full writeup + research citations: `docs/v2.8-automation-policy-and-enforcement.md`.

## What's new in v2.9 / v2.10 — reconciling three parallel builds

While the v2.6–v2.8 work above was in progress, three other sessions
pushed overlapping work directly to `main`. All three are merged in, with
14 real bugs found and fixed by actually running the merged code — not
trusting any "production ready" claims at face value (including a syntax
error that broke the entire backend's import, and a critical DuckDB
concurrency SIGSEGV fixed with a lock-serializing connection wrapper).
Full writeups: `docs/v2.9-batch1-reconciliation.md`,
`docs/v2.10-phase2-ui-bridge-reconciliation.md`.

## What's new in v3.0 — Ontology Engine + Maya-Vigesimal step-up auth

- **Ontology Engine** — a Palantir Foundry-style Object/Link digital twin
  (`backend/services/ontology_engine.py`, `/api/v3/ontology/*`). Every
  staged payload and containment action now materializes a real node in
  the graph (an `Asset` node per target, linked to the action), so the
  Approval Gate can show a basic attack-path/related-object view instead
  of an empty graph.
- **Maya-Vigesimal calendar 2FA** — an **internal high-assurance step-up
  authenticator for HIGH/CRITICAL actions only** (`backend/security_agents/exploit_agent.py`,
  `/api/v3/auth/maya/*`) — explicitly *not* login MFA. A real interlock,
  not a parallel confirmation step: `approve_payload()`/`reject_payload()`
  refuse to record a decision until the linked session's status is
  `'consumed'`, and every real remediation action (host quarantine/
  isolation, auto-staged containment) is gated the same way as an
  offensive payload. **Dual-mode display**: only friendly
  `display_issued_at`/`display_expires_at` timestamps and a masked token
  (reveal toggle) are ever shown by default — the actual Tzolkin/Haab
  calendar coordinates the token is derived from stay internal, surfaced
  only behind an explicit `?reveal_internal=true` auditor toggle.
- **PQC decision audit** — every stage/challenge/decision is ML-DSA-65-signed;
  `crypto.pqc_manager.verify_stored_entry()` re-verifies a *stored*
  signature against the exact public key/algorithm recorded at signing
  time (not a live process's own key, which is per-instance and not
  persisted) — surfaced per-payload as
  `original_pqc_signature_verification` in the enriched approval context.
- **Crypto-agility** — a `PQC_PROFILE` config flag (`"commercial"` default
  → ML-DSA-65; `"cnsa2"` → ML-DSA-87) abstracts the signer so no caller
  hardcodes a parameter set. Full policy: `docs/crypto-agility.md`.
- **Core loop visibility** — `GET /api/approval/{id}/context` (risk
  level, blast-radius summary, reversibility, Maya + authorization +
  ontology status, PQC verification result, a `staged → challenge_issued
  → challenge_consumed → approved/denied → executed_simulated` timeline)
  and `GET /api/approval/audit/recent` (recent high-risk decisions with
  re-verified signatures), mapped explicitly to the CISA Zero Trust
  Maturity Model (Policy Enforcement Point, continuous verification,
  least privilege, assume breach).
- **Progressive enhancements** — a thin prompt-driven playbook lookup
  over the existing IR playbook catalog (`POST /api/v3/aip/cheatsheet/chat`),
  read-only authorization-status visibility in the approval context,
  `GET /api/fabric/summary` (which of the 7 Fabric capabilities are
  active, from existing data), and finished quantum jobs optionally
  linking into the PQC audit trail.

Full writeup, the interlock-fix root cause, every bug found across
Phases 0–5, and deliberate scope decisions (no new `cheatsheet_playbooks`
table, no ML-KEM-1024, no forced CNSA 2.0):
`docs/v3.0-ontology-maya-enterprise.md`.

## What's new in Track A — Maya-gated containment hardening

Track A sits on top of v3.0. Containment is no longer "approved then fire
the webhook." Every isolate/quarantine now has to clear a **compliance
pre-flight** and is delivered through a **hardened EDR orchestrator**.

- **HIPAA / SOC2 / PCI-DSS constraints** — `backend/security_agents/compliance_constraints.py`.
  Geographic residency, critical-service availability, and cardholder-data
  environment hosts can block isolation before it is staged. Operators see
  the reason; an audit exception is required to proceed.
- **Hardened EDR orchestrator** — `backend/security_agents/edr_hardened.py`.
  Exponential backoff (1s → 4s → 16s), transient vs permanent error
  classification, compliance pre-check, then the existing Docker/webhook
  connectors.
- **Attack-path targeting** — `GET /api/response/related-targets` walks
  the Ontology Engine graph (depth 1–5) and returns related Asset nodes
  so multi-host remediation is not a guess.
- **New operator endpoints** — `GET /api/response/compliance/pre-check`
  and the existing `POST /api/response/actions/{id}/enforce` now go
  through the hardened orchestrator. The Live Ops Response panel runs
  the pre-check automatically before staging isolation.
- **Maya still gates the decision** — compliance and retry sit *in front
  of* enforcement; they do not replace the step-up authenticator.

Writeup: `docs/track-a-containment-hardening.md`. GitHub Pages (operator
UI, demo mode when the API is offline):
https://thepeoplesrealty100-ops.github.io/Enterprise-Application/
