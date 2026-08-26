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
"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel

try:
    from database import DuckDBManager
    from llm_energy_core import ENERGY_CORE
    _db: Optional[DuckDBManager] = DuckDBManager()
    QAIP_OK = True
except Exception as _e:
    QAIP_OK = False
    _QAIP_ERR = str(_e)
    _db = None
    ENERGY_CORE = None


class OrbitalCommRequest(BaseModel):
    event_type: str
    computational_agent_id: str = ""
    inference_chain_hash: str = ""
    quantum_entropy_seed: str = ""
    execution_latency_ms: int = 0


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
