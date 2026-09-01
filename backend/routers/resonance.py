"""
backend/routers/resonance.py
==============================
Resonance / Global Dashboard API router (JAKAL v2.4).

Fleet-wide posture (global_fleet_matrix) + a live snapshot of org-wide
security configuration (global_security_settings). The settings snapshot
is deliberately READ-ONLY-by-derivation: it's computed fresh from the
real operators/encryption_keys/pqc_audit_log tables (database.py's
resonance_settings_snapshot()) rather than being an independently
editable config blob that could drift out of sync with what's actually
enforced — see that method's docstring for why.

Endpoints:
  GET   /resonance/fleet                  — fleet matrix (optionally quarantined-only)
  POST  /resonance/fleet/host             — upsert one host's posture
  GET   /resonance/settings               — latest security-settings snapshot
  POST  /resonance/settings/snapshot      — take a fresh snapshot now
"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel

try:
    from database import DuckDBManager, get_db_manager
    _db: Optional[DuckDBManager] = get_db_manager()
    RESONANCE_OK = True
except Exception as _e:
    RESONANCE_OK = False
    _RESONANCE_ERR = str(_e)
    _db = None


class FleetHostRequest(BaseModel):
    machine_id: str
    network_segment: str = ""
    predictive_threat_score: float = 0.0
    resonance_load_metric: float = 0.0
    is_quarantined: bool = False


router = APIRouter(prefix="/resonance", tags=["resonance-global-dashboard"])


def _require():
    if not RESONANCE_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Resonance unavailable: {_RESONANCE_ERR}")


@router.get("/fleet")
def fleet_matrix(quarantined_only: bool = Query(False)):
    _require()
    fleet = _db.list_fleet_matrix(quarantined_only=quarantined_only)
    return {"count": len(fleet), "fleet": fleet}


@router.post("/fleet/host", status_code=http_status.HTTP_201_CREATED)
def upsert_fleet_host(req: FleetHostRequest):
    _require()
    machine_id = _db.upsert_fleet_host(req.model_dump())
    return {"machine_id": machine_id, "status": "recorded"}


@router.get("/settings")
def get_settings():
    _require()
    settings = _db.latest_security_settings()
    if not settings:
        # Nothing snapshotted yet — take one now rather than 404 on a
        # dashboard's very first load.
        settings = _db.resonance_settings_snapshot(str(uuid.uuid4()))
    return settings


@router.post("/settings/snapshot", status_code=http_status.HTTP_201_CREATED)
def snapshot_settings():
    _require()
    return _db.resonance_settings_snapshot(str(uuid.uuid4()))
