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

  v2.8 — Resonance Wave Automation, real write control:
  GET   /resonance/policy                 — list every automation policy knob
  POST  /resonance/policy/{key}           — set one (RBAC-gated, audited, PQC-signed)
  GET   /resonance/policy/stale-sandboxes — sandboxes older than sandbox_max_lifetime_hours

  These are deliberately NOT the same thing as /resonance/settings above --
  see resonance_policy's CREATE TABLE comment in database.py for why
  global_security_settings stays a derived, read-only snapshot while this
  is a real, independently-writable set of knobs that live enforcement
  points (response.py, vault.py, cheatsheet.py) actually read.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status as http_status
from pydantic import BaseModel

try:
    from database import DuckDBManager, get_db_manager
    _db: Optional[DuckDBManager] = get_db_manager()
    RESONANCE_OK = True
except Exception as _e:
    RESONANCE_OK = False
    _RESONANCE_ERR = str(_e)
    _db = None

from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)

# policy_key -> (default_value, value_type, label, description)
_DEFAULT_POLICY = [
    ("response_auto_stage_threshold", 0.8, "number", "Auto-stage containment threshold",
     "Triage severity (0-1) at or above which /api/response/triage auto-stages a containment "
     "approval request instead of just recommending. Per-request calls may still override it."),
    ("trade_secret_isolation_enforced", True, "bool", "Enforce Trade Secrets role isolation",
     "When on, POST /api/vault/items rejects an empty allowed_roles list -- every vault item "
     "must be explicitly scoped to at least one role, never implicitly world-readable."),
    ("auto_approve_low_risk_actions", False, "bool", "Auto-approve LOW-risk script executions",
     "When on, a LOW-risk gacyber_toolkit script staged via POST /cheatsheet/scripts/{id}/stage "
     "is approved automatically (still authorization-gated, still audited, still sandbox-only) "
     "instead of waiting on a human at POST /api/approval/{id}/approve. MEDIUM/HIGH/CRITICAL "
     "always require a human decision regardless of this setting."),
    ("sandbox_max_lifetime_hours", 24, "number", "Sandbox max lifetime (hours)",
     "Sandboxes older than this are surfaced by GET /resonance/policy/stale-sandboxes as due "
     "for review/destruction. Informational only -- nothing auto-destroys a sandbox."),
]


def _seed_policy():
    if not RESONANCE_OK:
        return
    for key, value, value_type, label, description in _DEFAULT_POLICY:
        _db.seed_policy(key, value, value_type, label, description)


_seed_policy()


def _audit(request: Request, user: dict, action: str, outcome: str, resource_id: str = "", detail=None):
    try:
        _db.insert_audit_entry({
            "actor_user_id": user["user_id"], "actor_label": user["username"],
            "action": action, "resource_type": "resonance_policy", "resource_id": resource_id,
            "outcome": outcome, "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("audit write failed for %s", action)


class PolicySetRequest(BaseModel):
    value: Any


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


# ══════════════════════════════════════════════════════════════════════════
# v2.8 — Resonance Wave Automation policy (real write control)
# ══════════════════════════════════════════════════════════════════════════

@router.get("/policy")
async def list_policy():
    _require()
    return {"policy": _db.list_policy()}


@router.post("/policy/{policy_key}", dependencies=[require_permission("response:manage")])
async def set_policy(policy_key: str, req: PolicySetRequest, request: Request,
                      user: dict = Depends(get_authenticated_user)):
    _require()
    try:
        ok = _db.set_policy_value(policy_key, req.value, user["username"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown policy key '{policy_key}'")

    try:
        from crypto.pqc_manager import PQCAuditManager
        pqc = PQCAuditManager()
        signed = pqc.sign_agent_action(
            agent_id="resonance-policy", operator_id=user["username"],
            action_payload={"policy_key": policy_key, "value": req.value},
        )
        _db.insert_pqc_audit_entry({
            "entry_id": signed["entry_id"], "agent_id": "resonance-policy",
            "operator_id": user["username"], "action_type": "policy_change",
            "action_detail": __import__("json").dumps({"policy_key": policy_key, "value": req.value}),
            "payload_hash": signed["payload_hash"], "pqc_signature": signed["pqc_signature"],
            "algorithm": signed["algorithm"], "public_key": signed["public_key"],
        })
    except Exception as e:
        logger.warning("PQC signing unavailable for policy change: %s", e)

    _audit(request, user, "policy_change", "success", policy_key, {"value": req.value})
    return {"status": "updated", "policy_key": policy_key, "value": req.value}


@router.get("/policy/stale-sandboxes")
async def stale_sandboxes():
    _require()
    max_hours = _db.get_policy_value("sandbox_max_lifetime_hours", 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
    rows = _db.conn.execute(
        "SELECT sandbox_id, container_name, name, image, status, operator_id, created_at "
        "FROM sandboxes WHERE status != 'destroyed' AND created_at < ? ORDER BY created_at ASC",
        (cutoff,),
    ).fetchall()
    cols = [d[0] for d in _db.conn.description]
    stale = [dict(zip(cols, r)) for r in rows]
    return {"max_lifetime_hours": max_hours, "stale_count": len(stale), "sandboxes": stale}
