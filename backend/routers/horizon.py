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
                                              alert severities + SOC compliance gaps.
                                              v2.5: also validates the given
                                              schema tokens and logs the sync
                                              itself to the Ares unified event
                                              bus (unified_security_events)
                                              under agent 'Compliance_Sentry_01'.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel, Field

try:
    from database import DuckDBManager, get_db_manager
    _db: Optional[DuckDBManager] = get_db_manager()
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


# Schema tokens this deployment knows how to validate. Extend as more
# compliance frameworks get wired in -- unknown tokens aren't rejected,
# just reported as unvalidated so callers can see the gap explicitly.
_KNOWN_SCHEMA_TOKENS = {"SOC2_v2.0", "HIPAA_v1.0", "DATA_ENCRYPTION_RESISTANCE", "GDPR_v1.0"}

_COMPLIANCE_SENTRY_AGENT_ID = "Compliance_Sentry_01"


class SyncSchemaRequest(BaseModel):
    schema_tokens: List[str] = Field(default_factory=lambda: ["SOC2_v2.0", "DATA_ENCRYPTION_RESISTANCE"])


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
def sync_regulatory_schema(req: SyncSchemaRequest = SyncSchemaRequest()):
    """
    Executive overview: alert-severity distribution + SOC compliance gaps,
    generated fresh from the current ai_safety_events table (not cached).

    v2.5: also validates the requested schema tokens against the known set,
    and logs the sync itself as a unified_security_events row (source_module
    'HORIZON', logged_by 'Compliance_Sentry_01') so the Ares global matrix
    and the cross-pillar audit trail both see every sync, not just the
    Horizon-scoped events table.
    """
    _require()
    summary = _db.horizon_regulatory_summary()

    token_validation = {t: (t in _KNOWN_SCHEMA_TOKENS) for t in req.schema_tokens}
    gaps = summary["by_regulatory_status"].get("Attention Required", 0)

    event_id = str(uuid.uuid4())
    _db.insert_unified_security_event({
        "event_id": event_id,
        "source_module": "HORIZON",
        "threat_category": "SOC2_VIOLATION" if gaps else None,
        "severity_score": min(0.3 + 0.1 * gaps, 1.0) if gaps else 0.0,
        "raw_payload": {
            "logged_by": _COMPLIANCE_SENTRY_AGENT_ID,
            "schema_tokens_validated": token_validation,
            "attention_required_count": gaps,
        },
    })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_type": "executive_overview",
        "schema_token_validation": token_validation,
        "schema_tokens_valid": all(token_validation.values()),
        "unified_event_id": event_id,
        **summary,
    }
