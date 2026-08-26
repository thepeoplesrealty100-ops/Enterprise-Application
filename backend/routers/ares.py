"""
backend/routers/ares.py
==========================
Ares Unified Control Plane API router (JAKAL v2.5).

Ties Horizon, Resonance/Q'AIP, and the Unified Security Fabric together
into one executive rollup, per the operator's Ares architecture directive.
This router owns no data of its own -- every field below is read from
tables/snapshot functions that already exist and are already the single
source of truth for their own domain: fabric_modules for fabric health,
horizon_trust_fabric_snapshot() for compliance/agent/threat counts, and
unified_security_events for the cross-pillar event bus itself.

Note on the directive's literal `/api/v1/ares/...` path: this app has no
versioned API surface anywhere else -- every other v2.x router mounts at a
plain /api/<name> prefix (see routers/__init__.py). This router follows
that same convention -- /api/ares/global-matrix-summary -- rather than
being the one endpoint with a `/v1/` segment nothing else has.

Endpoints:
  GET  /ares/global-matrix-summary  — fabric status, compliance %, active
                                       agents, threats blocked, and Horizon
                                       health flags (Shadow AI / SOC2 /
                                       adversarial defense / DLP) -- freshly
                                       derived on every call, never cached
  GET  /ares/unified-events         — list the raw cross-pillar event bus
"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status

try:
    from database import DuckDBManager
    _db: Optional[DuckDBManager] = DuckDBManager()
    ARES_OK = True
except Exception as _e:
    ARES_OK = False
    _ARES_ERR = str(_e)
    _db = None


router = APIRouter(prefix="/ares", tags=["ares-unified-control-plane"])


def _require():
    if not ARES_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Ares control plane unavailable: {_ARES_ERR}")


@router.get("/global-matrix-summary")
def global_matrix_summary():
    _require()
    snapshot = _db.horizon_trust_fabric_snapshot(str(uuid.uuid4()))
    return {
        "fabric_status": snapshot["fabric_status"],
        "compliance_coverage_pct": snapshot["compliance_coverage_pct"],
        "active_agent_count": snapshot["active_agent_count"],
        "threats_blocked_count": snapshot["threats_blocked_count"],
        "shadow_ai_status": snapshot["shadow_ai_status"],
        "soc2_compliance_status": snapshot["soc2_compliance_status"],
        "adversarial_defense_status": snapshot["adversarial_defense_status"],
        "dlp_status": snapshot["dlp_status"],
        "last_schema_sync": snapshot["last_schema_sync"],
        "dynamic_sync_regulatory_schema_trigger": "/api/horizon/sync-regulatory-schema",
        "recorded_at": snapshot["recorded_at"],
    }


@router.get("/unified-events")
def unified_events(
    source_module: Optional[str] = Query(None),
    threat_category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    _require()
    events = _db.list_unified_security_events(
        source_module=source_module, threat_category=threat_category, limit=limit
    )
    return {"count": len(events), "events": events}
