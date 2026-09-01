# backend/app.py
"""
JAKAL Backend - FastAPI application (v2.5)

Pure wiring layer: config, middleware, shared agents that are not owned by a
router, and the modular router mount points.

Also serves the operator UI from FRONTEND_DIR at / (same origin as the API).
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncio
import json as _json
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import get_config
from database import DuckDBManager
from llm_orchestrator import AgentOrchestrator
from tools.authorization import AuthorizationError
from security_agents.vm_orchestrator import VMOrchestrator
from security_agents.compliance_axiom import ComplianceAxiom
from security_agents.edr_mdr import EdrMdrEngine
from middleware import TimingAndSecurityMiddleware
from routers import (
    pentest_router, quantum_router, reports_router,
    crypto_router, payloads_router,
    aip_router, fabric_router,
    wireless_router, approval_router,
    horizon_router, canvas_router, resonance_router, qaip_router,
    ares_router, scripts_router,`n)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = get_config()

app = FastAPI(
    title="JAKAL Backend",
    version="2.5",
    description=(
        "JAKAL Enterprise Cybersecurity Platform — "
        "Post-Quantum Cryptography, Quantum Computing, AIP ontology-driven "
        "payload intelligence (cheatsheet-interwoven), Unified Security Fabric "
        "(Zero Trust 7-pillar), Threat Hunting, EDR/MDR, Compliance, VM Orchestration, "
        "Wireless (802.11) Assessment, a Human Approval Gate for high-risk payloads, "
        "Horizon AI-safety/regulatory events, Agentic Canvas patch deployment, "
        "Resonance fleet posture, Q'AIP quantum/LLM inference orchestration, and "
        "Ares — the unified control plane tying Horizon/Resonance/Fabric together."
    ),
)

app.add_middleware(TimingAndSecurityMiddleware)

_cors_origins = getattr(config, "CORS_ORIGINS", None) or [
    "http://localhost:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
if isinstance(_cors_origins, str):
    _cors_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # Any localhost / 127.0.0.1 port (PowerShell static server, Live Server, etc.)
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Modular routers ───────────────────────────────────────────────────────
app.include_router(pentest_router,   prefix="/api")
app.include_router(quantum_router,   prefix="/api")
app.include_router(reports_router,   prefix="/api")
app.include_router(crypto_router,    prefix="/api")
app.include_router(payloads_router,  prefix="/api")
app.include_router(aip_router,       prefix="/api")
app.include_router(fabric_router,    prefix="/api")
app.include_router(wireless_router,  prefix="/api")
app.include_router(approval_router,  prefix="/api")
app.include_router(horizon_router,   prefix="/api")
app.include_router(canvas_router,    prefix="/api")
app.include_router(resonance_router, prefix="/api")
app.include_router(qaip_router,      prefix="/api")
app.include_router(ares_router,     prefix="/api")`napp.include_router(scripts_router, prefix="/api")

db = DuckDBManager()
orchestrator = AgentOrchestrator(config)
vm_orchestrator = VMOrchestrator(db)
compliance_axiom = ComplianceAxiom(db)
edr_mdr = EdrMdrEngine(db)


def _row_field(row, key: str, index: int):
    """DuckDB rows may be dict-like or tuples depending on path."""
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[index]
    except Exception:
        return None


# ============================================================================
# HEALTH
# ============================================================================

@app.get("/health")
async def health_check():
    return {
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "duckdb",
        "llm_engine": getattr(config, "LLM_ENGINE", "unknown"),
        "version": app.version,
    }


@app.get("/api/health")
async def api_health_check():
    return {
        "status": "healthy",
        "service": "backend",
        "version": app.version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/llm/health")
async def llm_health():
    return {"engine": getattr(config, "LLM_ENGINE", "unknown"), "status": "configured"}


# ============================================================================
# SCOPE / AUTHORIZATION
# ============================================================================

@app.post("/api/scope/add")
async def add_scope(payload: dict):
    scope_id = db.add_scope(
        client_name=payload["client_name"],
        scope_definition=payload["scope_definition"],
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
        result = check_authorization_and_scope(
            payload["target"],
            "scope_check",
            payload.get("operator_id", "system"),
            db=db,
        )
        return result
    except AuthorizationError as e:
        raise HTTPException(status_code=403, detail=str(e))


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
# TELEMETRY SSE
# ============================================================================

@app.get("/api/telemetry/stream")
async def telemetry_stream():
    async def event_generator():
        last_id = None
        rows = db.query(
            "SELECT id, timestamp, event, action, status FROM agent_logs "
            "ORDER BY timestamp DESC LIMIT 50"
        )
        for row in reversed(rows or []):
            ts = _row_field(row, "timestamp", 1)
            event = _row_field(row, "event", 2)
            action = _row_field(row, "action", 3)
            status = _row_field(row, "status", 4)
            rid = _row_field(row, "id", 0)
            payload = _json.dumps({
                "message": "[{}] {} - {} ({})".format(ts, event, action, status),
                "timestamp": str(ts),
                "level_color": "text-emerald-400" if status == "success" else "text-red-400",
            })
            yield "data: {}\n\n".format(payload)
            last_id = rid
        while True:
            await asyncio.sleep(3)
            if last_id is not None:
                new_rows = db.query(
                    "SELECT id, timestamp, event, action, status FROM agent_logs "
                    "WHERE id > ? ORDER BY timestamp ASC LIMIT 20", (last_id,))
            else:
                new_rows = db.query(
                    "SELECT id, timestamp, event, action, status FROM agent_logs "
                    "ORDER BY timestamp ASC LIMIT 20")
            for row in new_rows or []:
                ts = _row_field(row, "timestamp", 1)
                event = _row_field(row, "event", 2)
                action = _row_field(row, "action", 3)
                status = _row_field(row, "status", 4)
                rid = _row_field(row, "id", 0)
                payload = _json.dumps({
                    "message": "[{}] {} - {} ({})".format(ts, event, action, status),
                    "timestamp": str(ts),
                    "level_color": "text-emerald-400" if status == "success" else "text-red-400",
                })
                yield "data: {}\n\n".format(payload)
                last_id = rid
    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============================================================================
# MITRE / VM / COMPLIANCE / EDR (unchanged contracts)
# ============================================================================

@app.get("/api/mitre/tactics")
async def get_mitre_tactics():
    return orchestrator.get_tactics()


@app.get("/api/mitre/techniques")
async def get_mitre_techniques(tactic: str):
    return orchestrator.get_techniques(tactic)


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


# ============================================================================
# FRONTEND (same origin as API — open http://localhost:8000/ )
# ============================================================================

_FRONTEND = Path(os.getenv(
    "FRONTEND_DIR",
    str(Path(__file__).resolve().parent.parent / "frontend"),
))


@app.get("/")
async def serve_index():
    index = _FRONTEND / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html")
    return {
        "service": "JAKAL Backend",
        "version": app.version,
        "docs": "/docs",
        "hint": "UI not bundled; open /docs or set FRONTEND_DIR",
    }


if _FRONTEND.is_dir():
    # Serves integration.js, gacyber_toolkit/*, etc. Must be registered last.
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
    logger.info("Frontend mounted from %s", _FRONTEND)
else:
    logger.warning("FRONTEND_DIR missing at %s — UI will not be served", _FRONTEND)


if __name__ == "__main__":
    host = getattr(config, "API_HOST", "0.0.0.0")
    port = int(getattr(config, "API_PORT", 8000))
    uvicorn.run(app, host=host, port=port, log_level="info")


