"""
backend/routers/horizon.py
============================
Horizon AI Safety Fabric API router (JAKAL v2.4).

An event stream + executive rollup for AI-safety / regulatory-compliance
signals (SOC 2, HIPAA, etc.) — separate from, and coarser-grained than,
the pentest-oriented Unified Security Fabric (v2.2): Horizon is about
"is our AI/automation posture compliant right now", Fabric is about
"are our 7 security capabilities healthy".

Endpoints:
  GET   /horizon/events                    — list recent AI-safety events
  POST  /horizon/events                    — record an AI-safety event
  POST  /horizon/sync-regulatory-schema    — executive JSON overview:
                                              alert severities + SOC compliance gaps
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel

try:
    from database import DuckDBManager
    _db: Optional[DuckDBManager] = DuckDBManager()
    HORIZON_OK = True
except Exception as _e:
    HORIZON_OK = False
    _HORIZON_ERR = str(_e)
    _db = None


class EventRequest(BaseModel):
    client_id: str
    soc_compliance_tier: str = "SOC2 Type II"
    protection_layer: str = "ai-agent-layer"
    alert_severity: int = 1
    regulatory_schema_status: str = "Syncing"


router = APIRouter(prefix="/horizon", tags=["horizon-ai-safety"])


def _require():
    if not HORIZON_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Horizon unavailable: {_HORIZON_ERR}")


@router.get("/events")
def list_events(client_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500)):
    _require()
    events = _db.list_ai_safety_events(client_id=client_id, limit=limit)
    return {"count": len(events), "events": events}


@router.post("/events", status_code=http_status.HTTP_201_CREATED)
def record_event(req: EventRequest):
    _require()
    event_id = str(uuid.uuid4())
    _db.insert_ai_safety_event({
        "event_id": event_id, "client_id": req.client_id,
        "soc_compliance_tier": req.soc_compliance_tier,
        "protection_layer": req.protection_layer,
        "alert_severity": req.alert_severity,
        "regulatory_schema_status": req.regulatory_schema_status,
    })
    return {"event_id": event_id, "status": "recorded"}


@router.post("/sync-regulatory-schema")
def sync_regulatory_schema():
    """Executive overview: alert-severity distribution + SOC compliance gaps,
    generated fresh from the current ai_safety_events table (not cached)."""
    _require()
    summary = _db.horizon_regulatory_summary()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_type": "executive_overview",
        **summary,
    }
