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
