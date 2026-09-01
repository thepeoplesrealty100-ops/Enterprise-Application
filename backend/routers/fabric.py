"""
backend/routers/fabric.py
=========================
Unified Security Fabric API router (JAKAL v2.2).

Consolidates the seven former micro-modules (MDR, Zero Trust, SASE, PAM,
DNS Filtering, Email Security, DLP) behind ONE control-plane API, scored on
the NSA/CISA Zero Trust Maturity ladder.

Endpoints:
  GET   /fabric/status                 — all capabilities + posture (single view)
  GET   /fabric/summary                — v3.0 Phase 4.3: light "which capabilities are
                                          active" view, derived from existing data only
  GET   /fabric/posture                — Zero Trust maturity posture (overall + per pillar)
  POST  /fabric/posture/snapshot       — persist a posture snapshot
  GET   /fabric/posture/history        — posture trend
  GET   /fabric/ontology               — Fabric ontology graph (objects + links)
  GET   /fabric/capability/{key}       — one capability's detail
  POST  /fabric/capability/{key}/maturity — set maturity level
  POST  /fabric/capability/{key}/status   — set operational status
  GET   /fabric/events                 — unified fabric event stream
  POST  /fabric/events                 — record a fabric event
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel

try:
    from security_agents.unified_fabric import UnifiedSecurityFabric, MATURITY_LEVELS
    from database import DuckDBManager, get_db_manager
    _db: Optional[DuckDBManager] = get_db_manager()
    _fabric = UnifiedSecurityFabric(db=_db)
    FABRIC_OK = True
except Exception as _e:
    FABRIC_OK = False
    _FABRIC_ERR = str(_e)
    _db = None
    _fabric = None


class MaturityRequest(BaseModel):
    maturity: str
    operator_id: str = "system"

class StatusRequest(BaseModel):
    status: str
    operator_id: str = "system"

class EventRequest(BaseModel):
    module_key: str
    event_type: str
    detail: str = ""
    severity: str = "info"
    operator_id: str = "system"


router = APIRouter(prefix="/fabric", tags=["unified-security-fabric"])


def _require():
    if not FABRIC_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Unified Security Fabric unavailable: {_FABRIC_ERR}")


@router.get("/status")
def fabric_status():
    """Full consolidated Fabric view — all seven capabilities + ZT posture in one call."""
    _require()
    return _fabric.status()


@router.get("/summary")
def fabric_summary():
    """v3.0 Phase 4.3: light summary of which of the 7 Fabric capabilities
    are currently considered active — see UnifiedSecurityFabric.capability_summary()."""
    _require()
    return _fabric.capability_summary()


@router.get("/posture")
def fabric_posture():
    """Zero Trust maturity posture: overall score/level + per-pillar breakdown."""
    _require()
    return _fabric.posture()


@router.post("/posture/snapshot", status_code=http_status.HTTP_201_CREATED)
def posture_snapshot(operator_id: str = Query("system")):
    """Persist a point-in-time posture snapshot for trend analysis."""
    _require()
    return _fabric.record_posture_snapshot(operator_id=operator_id)


@router.get("/posture/history")
def posture_history(limit: int = Query(30, ge=1, le=365)):
    """Return recent posture snapshots (trend)."""
    _require()
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    return {"assessments": _db.list_posture_assessments(limit=limit)}


@router.get("/ontology")
def fabric_ontology():
    """Fabric ontology graph (objects + links) for the AIP layer / dashboard."""
    _require()
    return _fabric.ontology_graph()


@router.get("/capability/{key}")
def get_capability(key: str):
    """Detail for one Fabric capability."""
    _require()
    cap = _fabric.get_capability(key)
    if not cap:
        raise HTTPException(status_code=404, detail=f"Unknown capability '{key}'")
    return cap


@router.post("/capability/{key}/maturity")
def set_capability_maturity(key: str, req: MaturityRequest):
    """Set a capability's Zero Trust maturity level."""
    _require()
    result = _fabric.set_maturity(key, req.maturity, operator_id=req.operator_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/capability/{key}/status")
def set_capability_status(key: str, req: StatusRequest):
    """Set a capability's operational status (active | degraded | disabled)."""
    _require()
    result = _fabric.set_status(key, req.status, operator_id=req.operator_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/events")
def fabric_events(module_key: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=500)):
    """Unified fabric event stream (optionally filtered by capability)."""
    _require()
    return {"events": _fabric.recent_events(module_key=module_key, limit=limit)}


@router.post("/events", status_code=http_status.HTTP_201_CREATED)
def record_fabric_event(req: EventRequest):
    """Record an event against a Fabric capability."""
    _require()
    return _fabric.record_event(
        req.module_key, req.event_type, req.detail,
        operator_id=req.operator_id, severity=req.severity,
    )
