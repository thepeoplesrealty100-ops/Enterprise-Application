"""
backend/routers/qaip.py
==========================
Q'AIP Logic & Quantum Orchestration API router (JAKAL v2.4).

Two things live here:
  - The Energy Core (llm_energy_core.py): a token-bucket throttle in front
    of LLM inference calls, currently wired into AIPPayloadGenerator's
    optional LLM-prioritization step (payloads/aip_payload_generator.py).
  - quantum_orbital_comms: a ledger of inference-chain / quantum-job
    events, logged automatically by the AIP prioritizer and available here
    for external tooling (e.g. a future quantum_engine.py hook) to log
    into via POST /qaip/orbital-comms.

Endpoints:
  GET   /qaip/energy-core/status   — current throttle load/allowed/throttled counts
  GET   /qaip/orbital-comms        — recent inference-chain / quantum-job events
  POST  /qaip/orbital-comms        — log an event (comm_id auto-generated)
  GET   /qaip/orbital-comms/stats  — aggregate stats (count, avg latency, by type)
  POST  /qaip/ingest-recon-intel   — v2.5 (Ares): score inbound recon/threat
                                      telemetry with threat_scoring.score_recon_finding(),
                                      log it to the unified event bus
                                      (unified_security_events), and -- only
                                      if severity crosses approval_threshold
                                      -- stage a pending approval_requests row
                                      via the same v2.3 Human Approval Gate
                                      every other high-risk action uses. See
                                      database.py's CREATE TABLE comment for
                                      why there's no second, parallel
                                      "agentic_approval_queue" table.
"""

import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel, Field

try:
    from database import DuckDBManager, get_db_manager
    from llm_energy_core import ENERGY_CORE
    from threat_scoring import score_recon_finding
    _db: Optional[DuckDBManager] = get_db_manager()
    QAIP_OK = True
except Exception as _e:
    QAIP_OK = False
    _QAIP_ERR = str(_e)
    _db = None
    ENERGY_CORE = None
    score_recon_finding = None


class OrbitalCommRequest(BaseModel):
    event_type: str
    computational_agent_id: str = ""
    inference_chain_hash: str = ""
    quantum_entropy_seed: str = ""
    execution_latency_ms: int = 0


class ReconIntelRequest(BaseModel):
    source_module: str = "GOD_S_EYE_RECON"
    target: str = ""
    threat_category: str = "EXPOSED_SERVICE"
    finding_summary: str = ""
    indicators: Dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "system"
    approval_threshold: float = 0.8


HIGH_SEVERITY_ACTION_TYPE = "qaip_recon_high_severity_response"

router = APIRouter(prefix="/qaip", tags=["qaip-quantum-orchestration"])


def _require():
    if not QAIP_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Q'AIP unavailable: {_QAIP_ERR}")


@router.get("/energy-core/status")
def energy_core_status():
    _require()
    return ENERGY_CORE.status()


@router.get("/orbital-comms")
def list_orbital_comms(event_type: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500)):
    _require()
    comms = _db.list_orbital_comms(event_type=event_type, limit=limit)
    return {"count": len(comms), "comms": comms}


@router.post("/orbital-comms", status_code=http_status.HTTP_201_CREATED)
def log_orbital_comm(req: OrbitalCommRequest):
    _require()
    comm_id = str(uuid.uuid4())
    _db.log_orbital_comm({"comm_id": comm_id, **req.model_dump()})
    return {"comm_id": comm_id, "status": "logged"}


@router.get("/orbital-comms/stats")
def orbital_comms_stats():
    _require()
    return _db.orbital_comms_stats()


@router.post("/ingest-recon-intel", status_code=http_status.HTTP_201_CREATED)
def ingest_recon_intel(req: ReconIntelRequest):
    """
    Ingest one recon/threat finding, score it with the Q'AIP severity
    heuristic (threat_scoring.score_recon_finding — deterministic, no LLM
    call), log it to unified_security_events, and -- only if severity_score
    exceeds req.approval_threshold -- stage a pending approval so nothing
    above the threshold auto-executes.
    """
    _require()
    if not ENERGY_CORE.allow():
        raise HTTPException(
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Q'AIP Energy Core throttled this request — retry shortly.",
        )

    start = time.monotonic()
    payload = req.model_dump()
    severity = score_recon_finding(payload)
    latency_ms = int((time.monotonic() - start) * 1000)

    event_id = str(uuid.uuid4())
    _db.insert_unified_security_event({
        "event_id": event_id,
        "source_module": req.source_module,
        "threat_category": req.threat_category,
        "severity_score": severity,
        "raw_payload": payload,
    })

    _db.log_orbital_comm({
        "comm_id": str(uuid.uuid4()),
        "event_type": "recon_intel_scoring",
        "computational_agent_id": "qaip-recon-scorer",
        "execution_latency_ms": latency_ms,
    })

    approval_request_id = None
    if severity > req.approval_threshold:
        approval_request_id = str(uuid.uuid4())
        _db.create_approval_request({
            "request_id": approval_request_id,
            "requested_by": req.requested_by,
            "action_type": HIGH_SEVERITY_ACTION_TYPE,
            "target": req.target,
            "risk_level": "CRITICAL",
            "summary": f"High-severity recon finding ({severity}) from {req.source_module}: {req.finding_summary}",
            "payload_detail": payload,
            "origin_module": req.source_module,
        })
        _db.link_unified_event_approval(event_id, approval_request_id)

    return {
        "event_id": event_id,
        "severity_score": severity,
        "requires_human_approval": approval_request_id is not None,
        "approval_request_id": approval_request_id,
        "status": "staged_pending_approval" if approval_request_id else "logged",
    }
