# JAKAL — Real Functionality Build (Sep 2026)

This pass replaced simulated actions with **real, tested** ones. Every item below
was verified running (FastAPI TestClient + live external calls) before delivery.
Route count: **370 → 386**.

## What became real

| # | Item | What it does now | Proof |
|---|------|------------------|-------|
| 1 | Cog → real routers | `patch:scan_cve` runs a **live OSV.dev** scan; `darkweb:run_recon` calls **real HIBP**; `fleet:isolate_host` calls the **real EDR connector**; agent-only actions return an honest `not_connected` instead of faking success | live CVEs w/ real CVSS |
| 2 | API-Key Vault | Settings → **Integrations** panel; keys encrypted at rest (AES-256-GCM); saving a key activates the module immediately | HIBP flips on when key saved |
| 3 | Threat-Intel lookup | Live IP/domain/URL/hash enrichment. **Keyless** Feodo + Tor work out of the box; VirusTotal/AbuseIPDB/OTX enrich when keys added | Feodo C2 → malicious 95; Tor → suspicious |
| 4 | Endpoint agent | Real hub-and-spoke: `agent/jakal_agent.py` registers, heartbeats, reports inventory, runs queued commands | real agent ran over HTTP, 42 pkgs |
| 5 | Asset detail | Fleet panel + asset drawer: real inventory + live CVEs + action buttons | Target B renders from real data |
| 6 | Endpoint CVE scan | Agent's reported software is scanned live via OSV.dev on the asset detail | 3 crit / 9 high on test host |
| 7 | SOAR chain | `POST /api/soar/auto-triage`: enrich → (if malicious) isolate → ticket, each step real, logged | live C2 IP → open ticket |

## Run it

```bash
cd backend
python -m venv .venv && . .venv/bin/activate    # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
# set a stable master key so encrypted keys survive restarts:
#   backend/.env  ->  JAKAL_MASTER_KEY=<any long random string>
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```
Open http://localhost:8000 . Bottom-left launcher: **◤ Fleet · ◇ Threat Intel · ⚙ Integrations**.

### Try it immediately (no keys needed)
- **Threat Intel** → paste `162.243.103.246` (or any IP) → Check. Feodo + Tor return a live verdict.
- **Integrations** → paste an AbuseIPDB/VirusTotal/OTX key → Save → threat-intel now enriches deeper.

### Enroll this machine as a managed endpoint
```bash
pip install requests psutil
python agent/jakal_agent.py --server http://localhost:8000
```
It appears under **Fleet** as a live device; open it to see inventory + live CVEs.

## New API surface
`/api/threatintel/lookup` · `/api/integrations/*` · `/api/agents/*` · `/api/soar/auto-triage`
plus a new cog action `intel:lookup`.

## Honesty notes (by design)
- Unconfigured integrations return `not_connected`, never fake data.
- `fleet:isolate_host` reports `not_configured` until an EDR webhook (Integrations),
  a Docker sandbox, or the agent's isolation path is present — it never fakes containment.
- Integrations write endpoints are open for the localhost single-operator model
  (matching the existing `/api/capabilities` surface). **Before any non-local
  deployment, put the app behind the existing IAM auth layer / network controls.**

## Not done this pass (largest remaining)
- **AI tool-calling**: the operator-console assistant invoking these real actions
  (the actions are now callable; wiring the LLM is the remaining step).
- **Non-PyPI inventory + NVD/CPE engine**: OS/application CVEs beyond package
  ecosystems (Windows apps, OS patches) — add an NVD/CPE matcher beside OSV.dev.
- **Agent hardening**: signed enrollment tokens, TLS pinning, mTLS.
