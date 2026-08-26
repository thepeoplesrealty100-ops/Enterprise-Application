# backend/app.py
"""
JAKAL Backend - FastAPI application

Wires together: DuckDBManager, AgentOrchestrator (LLM/MITRE), QuantumEngine,
and the ReconAgent / EnumAgent / WebAgent / ReportAgent pipeline.

Note on scope vs. the original architecture doc: the doc's /api/pentest/start
staged exploit payloads for human approval. This version stops the automated
pipeline at reporting -- recon -> enumeration -> web checks -> report -- and
does not stage or execute exploit payloads. See README_FIXES.md for why, and
for the suggested shape of a human-directed "next steps" stub if you want one.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import asyncio
import json as _json
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from database import DuckDBManager
from llm_orchestrator import AgentOrchestrator
from quantum_engine import QuantumEngine
from tools.authorization import AuthorizationError
from security_agents.recon_agent import ReconAgent
from security_agents.enum_agent import EnumAgent
from security_agents.web_agent import WebAgent
from security_agents.report_agent import ReportAgent
from security_agents.vm_orchestrator import VMOrchestrator
from security_agents.compliance_axiom import ComplianceAxiom
from security_agents.edr_mdr import EdrMdrEngine
from security_agents.wireless_agent import WirelessAgent
from security_agents.exploit_agent import ExploitAgent
from middleware import TimingAndSecurityMiddleware
from routers import (
    pentest_router, quantum_router, reports_router,
    crypto_router, payloads_router,
    aip_router, fabric_router,
    wireless_router, approval_router,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="JAKAL Backend",
    version="2.3",
    description=(
        "JAKAL Enterprise Cybersecurity Platform — "
        "Post-Quantum Cryptography, Quantum Computing, AIP ontology-driven "
        "payload intelligence (cheatsheet-interwoven), Unified Security Fabric "
        "(Zero Trust 7-pillar), Threat Hunting, EDR/MDR, Compliance, VM Orchestration, "
        "Wireless (802.11) Assessment, and a Human Approval Gate for high-risk payloads."
    ),
)

# Security + timing headers on every response
app.add_middleware(TimingAndSecurityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # add your deployed frontend origin(s)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Modular routers (v2.0 + v2.1) ─────────────────────────────────────────
app.include_router(pentest_router,  prefix="/api")
app.include_router(quantum_router,  prefix="/api")
app.include_router(reports_router,  prefix="/api")
app.include_router(crypto_router,   prefix="/api")   # v2.1 PQC + encryption
app.include_router(payloads_router, prefix="/api")   # v2.1 payload gen + playbooks + threat intel
app.include_router(aip_router,      prefix="/api")   # v2.2 AIP ontology payload gen (cheatsheet interweave)
app.include_router(fabric_router,   prefix="/api")   # v2.2 Unified Security Fabric (7 capabilities)
app.include_router(wireless_router, prefix="/api")   # v2.3 passive Wi-Fi survey
app.include_router(approval_router, prefix="/api")   # v2.3 Human Approval Gate


class _Config:
    """Minimal config placeholder -- replace with real env-var loading
    (e.g. pydantic-settings) before production use."""
    LLM_ENGINE = "ollama"  # or "gemini" -- set GEMINI_API_KEY below if so
    GEMINI_API_KEY = None
    GEMINI_MODEL = "gemini-1.5-flash"
    OLLAMA_MODEL = "llama3"
    OLLAMA_BASE_URL = "http://localhost:11434"
    IBM_QUANTUM_TOKEN = None
    IBM_QUANTUM_CHANNEL = "ibm_quantum"
    IBM_BACKEND_NAME = None
    NMAP_TIMEOUT = 120
    NUCLEI_TIMEOUT = 120
    NUCLEI_TEMPLATES_PATH = None


config = _Config()
db = DuckDBManager()
orchestrator = AgentOrchestrator(config)
quantum = QuantumEngine(config)
recon = ReconAgent(db, config)
enum_agent = EnumAgent(db, config)
web_agent = WebAgent(db, config)
report_agent = ReportAgent(db, orchestrator)
vm_orchestrator = VMOrchestrator(db)
compliance_axiom = ComplianceAxiom(db)
edr_mdr = EdrMdrEngine(db)
wireless_agent = WirelessAgent(db, config)      # v2.3 — 802.11 passive assessment
exploit_agent = ExploitAgent(db, config)        # v2.3 — Human Approval Gate backend


# ============================================================================
# HEALTH
# ============================================================================

@app.get("/health")
async def health_check():
    return {
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "duckdb",
        "llm_engine": config.LLM_ENGINE,
    }


@app.get("/api/health")
async def api_health_check():
    """Aliased health endpoint under /api prefix for router-consistent access."""
    return {
        "status": "healthy",
        "service": "backend",
        "version": "2.2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/llm/health")
async def llm_health():
    return {"engine": config.LLM_ENGINE, "status": "configured"}


@app.get("/api/quantum/health")
async def quantum_health():
    from quantum_engine import QISKIT_AVAILABLE
    return {"qiskit_available": QISKIT_AVAILABLE, "ibm_service_connected": quantum.ibm_service is not None}


# ============================================================================
# SCOPE / AUTHORIZATION
# ============================================================================

@app.post("/api/scope/add")
async def add_scope(payload: dict):
    """Register an authorized engagement scope. Do this BEFORE running anything
    against a target -- every agent call is blocked without a matching row here."""
    scope_id = db.add_scope(
        client_name=payload["client_name"],
        scope_definition=payload["scope_definition"],  # e.g. "203.0.113.0/24, staging.client.com"
        start_date=datetime.fromisoformat(payload["start_date"]),
        end_date=datetime.fromisoformat(payload["end_date"]),
        roe_document_path=payload.get("roe_document_path"),
    )
    return {"scope_id": scope_id, "status": "created"}


@app.post("/api/insurance/add")
async def add_insurance(payload: dict):
    policy_id = db.add_insurance_policy(
        policy_number=payload["policy_number"],
        provider=payload["provider"],
        coverage_amount=payload["coverage_amount"],
        expiry=datetime.fromisoformat(payload["expiry"]),
    )
    return {"policy_id": policy_id, "status": "created"}


@app.post("/api/scope/validate")
async def validate_scope(payload: dict):
    from tools.authorization import check_authorization_and_scope
    try:
        result = check_authorization_and_scope(payload["target"], "scope_check", payload.get("operator_id", "system"), db=db)
        return result
    except AuthorizationError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ============================================================================
# QUANTUM
# ============================================================================

@app.post("/api/quantum/submit")
async def submit_quantum_job(job: dict):
    circuit_name = job.get("circuit", "bell_state")
    shots = job.get("shots", 1024)
    backend_name = job.get("backend", "qiskit_aer")
    result = quantum.run_circuit(circuit_name, shots, backend_name)
    job_id = quantum.store_result(result)
    return {"job_id": job_id, "result": result}


@app.get("/api/quantum/jobs/{job_id}")
async def get_quantum_job(job_id: str):
    result = quantum.retrieve_result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="job not found")
    return result


@app.get("/api/quantum/risk-panel")
async def quantum_risk_panel():
    """Illustrative dashboard panel -- see quantum_engine.py docstring."""
    return quantum.quantum_risk_panel()


# ============================================================================
# PENTEST WORKFLOW (recon -> enumeration -> web checks -> report)
# ============================================================================

@app.post("/api/pentest/run")
async def run_pentest(config_payload: dict):
    """
    Runs the fully-automatable portion of the pipeline end to end:
    recon -> enumeration -> web checks -> report.

    Every stage independently re-checks authorization/scope -- this is
    intentional defense in depth, not redundancy to remove.
    """
    target = config_payload["target"]
    scan_type = config_payload.get("scan_type", "comprehensive")
    operator_id = config_payload.get("operator_id", "system")
    include_quantum_panel = config_payload.get("include_quantum_panel", False)

    try:
        recon_results = recon.scan(target, scan_type, operator_id)
        enum_results = enum_agent.enumerate(target, recon_results.get("open_ports", []), operator_id)
        web_results = web_agent.scan(target, operator_id)

        attack_mappings = orchestrator.map_to_attack_framework(recon_results)

        quantum_panel = quantum.quantum_risk_panel() if include_quantum_panel else None

        report = report_agent.generate(
            target=target,
            recon_results=recon_results,
            enum_results=enum_results,
            web_results=web_results,
            quantum_panel=quantum_panel,
            operator_id=operator_id,
        )

        test_id = db.insert_pentest({
            "target": target,
            "scan_type": scan_type,
            "recon_results": recon_results,
            "attack_mappings": attack_mappings,
            "staged_exploits": [],  # intentionally empty -- see module docstring
            "status": "report_ready",
        })

        return {
            "test_id": test_id,
            "status": "report_ready",
            "report": report,
            "report_markdown": report_agent.to_markdown(report),
        }

    except AuthorizationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Pentest run failed")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# AGENT LOGS
# ============================================================================

@app.get("/api/agent/logs")
async def get_agent_logs(limit: int = 50, offset: int = 0):
    rows = db.query(
        "SELECT id, timestamp, event, action, status, operator_id, details "
        "FROM agent_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return {"logs": rows, "count": len(rows)}


# ============================================================================
# TELEMETRY SSE  (consumed by integration.js startTelemetryStream)
# ============================================================================

@app.get("/api/telemetry/stream")
async def telemetry_stream():
    """Server-Sent Events — streams recent agent logs then live updates every 3s."""
    async def event_generator():
        last_id = None
        rows = db.query(
            "SELECT id, timestamp, event, action, status FROM agent_logs "
            "ORDER BY timestamp DESC LIMIT 50"
        )
        for row in reversed(rows):
            payload = _json.dumps({
                "message": "[{}] {} - {} ({})".format(
                    row["timestamp"], row["event"], row["action"], row["status"]),
                "timestamp": row["timestamp"],
                "level_color": "text-emerald-400" if row["status"] == "success" else "text-red-400",
            })
            yield "data: {}\n\n".format(payload)
            last_id = row["id"]
        while True:
            await asyncio.sleep(3)
            if last_id:
                new_rows = db.query(
                    "SELECT id, timestamp, event, action, status FROM agent_logs "
                    "WHERE id > ? ORDER BY timestamp ASC LIMIT 20", (last_id,))
            else:
                new_rows = db.query(
                    "SELECT id, timestamp, event, action, status FROM agent_logs "
                    "ORDER BY timestamp ASC LIMIT 20")
            for row in new_rows:
                payload = _json.dumps({
                    "message": "[{}] {} - {} ({})".format(
                        row["timestamp"], row["event"], row["action"], row["status"]),
                    "timestamp": row["timestamp"],
                    "level_color": "text-emerald-400" if row["status"] == "success" else "text-red-400",
                })
                yield "data: {}\n\n".format(payload)
                last_id = row["id"]
    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============================================================================
# MITRE
# ============================================================================


@app.get("/api/mitre/tactics")
async def get_mitre_tactics():
    return orchestrator.get_tactics()


@app.get("/api/mitre/techniques")
async def get_mitre_techniques(tactic: str):
    return orchestrator.get_techniques(tactic)


# ============================================================================
# VM ORCHESTRATOR (local lab/sandbox containers only -- see module docstring)
# ============================================================================

@app.get("/api/vm/images")
async def vm_list_images():
    return vm_orchestrator.list_images()


@app.post("/api/vm/sandboxes")
async def vm_create_sandbox(payload: dict):
    result = vm_orchestrator.create_sandbox(
        name=payload.get("name", "unnamed"),
        image_key=payload.get("image_key", "ubuntu-lab"),
        operator_id=payload.get("operator_id", "system"),
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/vm/sandboxes")
async def vm_list_sandboxes():
    return {"sandboxes": vm_orchestrator.list_sandboxes()}


@app.post("/api/vm/sandboxes/{container_name}/exec")
async def vm_exec_sandbox(container_name: str, payload: dict):
    result = vm_orchestrator.exec_in_sandbox(
        container_name, payload.get("command", ""), payload.get("operator_id", "system")
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.delete("/api/vm/sandboxes/{container_name}")
async def vm_destroy_sandbox(container_name: str, operator_id: str = "system"):
    result = vm_orchestrator.destroy_sandbox(container_name, operator_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ============================================================================
# QUANTUM COMPLIANCE AXIOM
# ============================================================================

@app.get("/api/compliance/axiom/frameworks")
async def compliance_frameworks():
    return compliance_axiom.available_frameworks()


@app.post("/api/compliance/axiom/report")
async def compliance_generate_report(payload: dict):
    result = compliance_axiom.generate_report(
        framework=payload.get("framework", "NIST_CSF"),
        findings=payload.get("findings", []),
        scope_id=payload.get("scope_id"),
        operator_id=payload.get("operator_id", "system"),
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ============================================================================
# ADVANCED EDR / MDR: PLAYBOOK LIBRARY
# ============================================================================

@app.post("/api/edr/playbooks/seed")
async def edr_seed_playbooks(operator_id: str = "system"):
    return edr_mdr.seed_default_playbooks(operator_id)


@app.get("/api/edr/playbooks")
async def edr_list_playbooks():
    return {"playbooks": edr_mdr.list_playbooks()}


@app.post("/api/edr/playbooks/{playbook_key}/execute")
async def edr_execute_playbook(playbook_key: str, payload: dict):
    result = edr_mdr.start_execution(
        playbook_key, payload.get("context", ""), payload.get("operator_id", "system")
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/edr/executions/{execution_id}/steps/{step_index}")
async def edr_complete_step(execution_id: int, step_index: int, payload: dict):
    return edr_mdr.complete_step(
        execution_id, step_index, payload.get("notes", ""), payload.get("operator_id", "system")
    )


@app.post("/api/edr/executions/{execution_id}/finish")
async def edr_finish_execution(execution_id: int, operator_id: str = "system"):
    return edr_mdr.finish_execution(execution_id, operator_id)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
