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
