"""
backend/routers/resonance.py
==============================
Resonance / Global Dashboard API router (JAKAL v2.5).

Enhanced with:
  • Policy-driven host isolation (resonance_policy table)
  • Enforcement engine integration (HMAC-SHA256 signing)
  • Webhook dispatcher (external SOC/SIEM integration)
  • Immutable audit trails
  • Script library integration

Fleet-wide posture (global_fleet_matrix) + enforcement automation.

Endpoints:
  GET   /resonance/fleet                  — fleet matrix (optionally quarantined-only)
  POST  /resonance/fleet/host             — upsert one host's posture
  GET   /resonance/settings               — latest security-settings snapshot
  POST  /resonance/settings/snapshot      — take a fresh snapshot now

  v2.8 — Resonance Wave Automation, real write control:
  GET   /resonance/automation-settings                 — list every automation policy knob
  POST  /resonance/automation-settings/{key}           — set one (RBAC-gated, audited, PQC-signed)
  GET   /resonance/automation-settings/stale-sandboxes — sandboxes older than sandbox_max_lifetime_hours

  NOTE: named "automation-settings" (not "policy") and backed by the
  automation_settings table specifically to avoid colliding with a
  separate, differently-shaped resonance_policy/"policies" concept
  merged in below from a parallel build (see database.py's
  automation_settings CREATE TABLE comment for the full reconciliation
  note).

  These are deliberately NOT the same thing as /resonance/settings above --
  see automation_settings's CREATE TABLE comment in database.py for why
  global_security_settings stays a derived, read-only snapshot while this
  is a real, independently-writable set of knobs that live enforcement
  points (response.py, vault.py, cheatsheet.py) actually read.

  Merged from a parallel build ("Batch 1") -- named isolation POLICY
  objects (plural, distinct from the automation-settings KNOBS above) plus
  a staged/audited enforcement workflow and an immutable audit trail:
  GET    /resonance/policies                   — list all isolation policies
  POST   /resonance/policies                   — create new policy
  GET    /resonance/policies/{id}              — get policy details
  PUT    /resonance/policies/{id}               — update policy
  DELETE /resonance/policies/{id}               — delete policy

  POST  /resonance/enforce/simulate           — dry-run isolation (impact analysis)
  POST  /resonance/enforce/request            — request approval for isolation
  POST  /resonance/enforce/execute            — execute isolation (post-approval)
  POST  /resonance/enforce/release            — release active isolation
  GET   /resonance/enforce/{id}/status        — check isolation status
  GET   /resonance/audit                      — immutable audit trail
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status as http_status
from pydantic import BaseModel

try:
    from database import DuckDBManager, get_db_manager
    _db: Optional[DuckDBManager] = get_db_manager()
    RESONANCE_OK = True
except Exception as _e:
    RESONANCE_OK = False
    _RESONANCE_ERR = str(_e)
    _db = None

# Batch 1's policy-enforcement stack (core/enforcement.py,
# core/webhook_dispatcher.py, core/audit_logger.py) -- imported and
# instantiated independently of the block above, and independently of
# EACH OTHER. Before this reconciliation, a single shared try/except
# wrapped ALL of this together with the fleet/settings/automation-settings
# endpoints above, so one missing optional dependency (webhook_dispatcher.py
# imported `aiohttp` unconditionally, never added to requirements.txt) took
# down the entire /resonance router, including endpoints that had nothing
# to do with it. See requirements.txt / core/webhook_dispatcher.py for the
# aiohttp fix itself.
try:
    from core.enforcement import AuditedHostIsolationEngine, IsolationMode, IsolationTrigger, IsolationAction
    _enforcement_engine: Optional["AuditedHostIsolationEngine"] = AuditedHostIsolationEngine(_db) if RESONANCE_OK else None
    ENFORCEMENT_OK = _enforcement_engine is not None
    _ENFORCEMENT_ERR = None if ENFORCEMENT_OK else "database unavailable"
except Exception as _e2:
    ENFORCEMENT_OK = False
    _ENFORCEMENT_ERR = str(_e2)
    _enforcement_engine = None
    IsolationMode = IsolationTrigger = IsolationAction = None

try:
    from core.webhook_dispatcher import WebhookDispatcher
    _webhook_dispatcher: Optional["WebhookDispatcher"] = WebhookDispatcher(_db) if RESONANCE_OK else None
except Exception:
    _webhook_dispatcher = None

try:
    from core.audit_logger import AuditLogger
    _audit_logger: Optional["AuditLogger"] = AuditLogger(_db) if RESONANCE_OK else None
    AUDIT_LOGGER_OK = _audit_logger is not None
    _AUDIT_LOGGER_ERR = None if AUDIT_LOGGER_OK else "database unavailable"
except Exception as _e4:
    AUDIT_LOGGER_OK = False
    _AUDIT_LOGGER_ERR = str(_e4)
    _audit_logger = None


def _safe_audit_log(**kwargs):
    """Best-effort call into Batch 1's AuditLogger -- never let a broken or
    unavailable immutable-audit-trail write take down the actual enforcement
    action it's trying to record. Mirrors this file's own `_audit()`
    helper's try/except-and-log pattern below."""
    if not _audit_logger:
        return
    try:
        _audit_logger.log(**kwargs)
    except Exception:
        logger.exception("resonance audit_logger.log failed for event_type=%s", kwargs.get("event_type"))

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
     "Sandboxes older than this are surfaced by GET /resonance/automation-settings/stale-sandboxes as due "
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
            "action": action, "resource_type": "automation_settings", "resource_id": resource_id,
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


class RessonancePolicyRequest(BaseModel):
    """Policy for automated host isolation."""
    policy_name: str
    description: Optional[str] = None
    
    # Trigger conditions
    threat_threshold: float = 0.7  # Isolation triggered at this severity
    trigger_type: str = "threat_detection"  # threat_detection, compliance_breach, etc.
    
    # Isolation mode
    isolation_mode: str = "network_only"  # network_only, full_isolation
    
    # Automation
    auto_enforce: bool = False  # Skip approval gate if True
    webhook_url: Optional[str] = None  # Send signed webhooks to this URL
    
    # Expiry
    enabled: bool = True


class IsolationSimulationRequest(BaseModel):
    """Request for isolation dry-run."""
    target_hostname: str
    target_ip_address: str
    target_os: str
    threat_severity: float = 0.5
    isolation_mode: str = "network_only"


class IsolationEnforcementRequest(BaseModel):
    """Request for enforced isolation."""
    target_hostname: str
    target_ip_address: str
    target_os: str
    threat_indicator: Optional[str] = None
    threat_severity: float = 0.5
    mitre_technique: Optional[str] = None
    regulatory_context: Optional[str] = None
    justification: str
    isolation_mode: str = "network_only"
    requested_by: str
    auto_approve: bool = False  # If true, execute immediately (admin only)


class IsolationApprovalRequest(BaseModel):
    """Request approval for an isolation."""
    isolation_id: str
    requestor: str
    reason: str = ""


class IsolationReleaseRequest(BaseModel):
    """Request to release an isolation."""
    isolation_id: str
    released_by: str


router = APIRouter(prefix="/resonance", tags=["resonance-enforcement"])


def _require():
    """Check that Resonance is operational."""
    if not RESONANCE_OK:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resonance unavailable: {_RESONANCE_ERR}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Original Endpoints (v2.4)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/fleet")
def fleet_matrix(quarantined_only: bool = Query(False)):
    """Get current fleet posture matrix."""
    _require()
    fleet = _db.list_fleet_matrix(quarantined_only=quarantined_only)
    return {"count": len(fleet), "fleet": fleet}


@router.post("/fleet/host", status_code=http_status.HTTP_201_CREATED)
def upsert_fleet_host(req: FleetHostRequest):
    """Upsert a single host's posture data."""
    _require()
    machine_id = _db.upsert_fleet_host(req.model_dump())
    _safe_audit_log(
        event_type="fleet_host_upserted",
        action="upsert_fleet_host",
        resource=machine_id,
        details={"threat_score": req.predictive_threat_score},
    )
    return {"machine_id": machine_id, "status": "recorded"}


@router.get("/settings")
def get_settings():
    """Get latest security settings snapshot."""
    _require()
    settings = _db.latest_security_settings()
    if not settings:
        settings = _db.resonance_settings_snapshot(str(uuid.uuid4()))
    return settings


@router.post("/settings/snapshot", status_code=http_status.HTTP_201_CREATED)
def snapshot_settings():
    """Take a fresh security settings snapshot."""
    _require()
    return _db.resonance_settings_snapshot(str(uuid.uuid4()))


# ══════════════════════════════════════════════════════════════════════════
# v2.8 — Resonance Wave Automation policy (real write control)
# ══════════════════════════════════════════════════════════════════════════

@router.get("/automation-settings")
async def list_policy():
    _require()
    return {"policy": _db.list_policy()}


@router.post("/automation-settings/{policy_key}", dependencies=[require_permission("response:manage")])
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


@router.get("/automation-settings/stale-sandboxes")
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


def _require_enforcement():
    """Guard for the /policies and /enforce/* endpoints below (Batch 1's
    stack). Distinct from `_require()`, which only checks _db -- these
    endpoints additionally need _enforcement_engine (core/enforcement.py),
    and /enforce/execute additionally passes _webhook_dispatcher (which is
    allowed to be None -- AuditedHostIsolationEngine.enforce_isolation
    already no-ops the webhook step when it is)."""
    _require()
    if not ENFORCEMENT_OK:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resonance policy-enforcement stack unavailable: {_ENFORCEMENT_ERR}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# v2.5 Enhanced: Policy Management
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/policies")
def list_policies(enabled_only: bool = Query(True)):
    """List all resonance policies."""
    _require()
    try:
        # Query from resonance_policy table (to be added to database.py)
        clause = "WHERE enabled = true" if enabled_only else ""
        rows = _db.conn.execute(
            f"SELECT id, policy_name, description, threat_threshold, trigger_type, isolation_mode, auto_enforce, webhook_url, enabled, created_at FROM resonance_policy {clause} ORDER BY created_at DESC"
        ).fetchall()
        
        policies = []
        for r in rows:
            policies.append({
                "id": r[0],
                "policy_name": r[1],
                "description": r[2],
                "threat_threshold": r[3],
                "trigger_type": r[4],
                "isolation_mode": r[5],
                "auto_enforce": r[6],
                "webhook_url": r[7],
                "enabled": r[8],
                "created_at": r[9],
            })
        
        return {"count": len(policies), "policies": policies}
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to list policies: {str(e)}")


@router.post("/policies", status_code=http_status.HTTP_201_CREATED)
def create_policy(req: RessonancePolicyRequest):
    """Create a new resonance policy."""
    _require()
    try:
        policy_id = str(uuid.uuid4())
        _db.conn.execute(
            """
            INSERT INTO resonance_policy
                (policy_id, policy_name, description, threat_threshold, trigger_type,
                 isolation_mode, auto_enforce, webhook_url, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy_id,
                req.policy_name,
                req.description,
                req.threat_threshold,
                req.trigger_type,
                req.isolation_mode,
                req.auto_enforce,
                req.webhook_url,
                req.enabled,
            ),
        )
        _db.conn.commit()
        
        _safe_audit_log(
            event_type="policy_created",
            action="create_resonance_policy",
            resource=policy_id,
            details={"policy_name": req.policy_name},
        )
        
        return {
            "policy_id": policy_id,
            "policy_name": req.policy_name,
            "status": "created",
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create policy: {str(e)}")


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str):
    """Get policy details."""
    _require()
    try:
        row = _db.conn.execute(
            "SELECT id, policy_id, policy_name, description, threat_threshold, trigger_type, isolation_mode, auto_enforce, webhook_url, enabled, created_at FROM resonance_policy WHERE policy_id = ?",
            (policy_id,),
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
        
        return {
            "id": row[0],
            "policy_id": row[1],
            "policy_name": row[2],
            "description": row[3],
            "threat_threshold": row[4],
            "trigger_type": row[5],
            "isolation_mode": row[6],
            "auto_enforce": row[7],
            "webhook_url": row[8],
            "enabled": row[9],
            "created_at": row[10],
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch policy: {str(e)}")


@router.put("/policies/{policy_id}")
def update_policy(policy_id: str, req: RessonancePolicyRequest):
    """Update a policy."""
    _require()
    try:
        # UPDATE ... RETURNING against a nextval()-default primary key
        # throws a spurious duplicate-key ConstraintException on the
        # duckdb==0.10.0 pin in requirements.txt (see
        # database.py's rotate_encryption_key() for the full writeup) --
        # check existence first, then a plain UPDATE.
        exists = _db.conn.execute(
            "SELECT 1 FROM resonance_policy WHERE policy_id = ?", (policy_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

        _db.conn.execute(
            """
            UPDATE resonance_policy
            SET policy_name = ?, description = ?, threat_threshold = ?,
                trigger_type = ?, isolation_mode = ?, auto_enforce = ?,
                webhook_url = ?, enabled = ?
            WHERE policy_id = ?
            """,
            (
                req.policy_name,
                req.description,
                req.threat_threshold,
                req.trigger_type,
                req.isolation_mode,
                req.auto_enforce,
                req.webhook_url,
                req.enabled,
                policy_id,
            ),
        )
        _db.conn.commit()

        _safe_audit_log(
            event_type="policy_updated",
            action="update_resonance_policy",
            resource=policy_id,
        )

        return {"policy_id": policy_id, "status": "updated"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update policy: {str(e)}")


@router.delete("/policies/{policy_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def delete_policy(policy_id: str):
    """Delete a policy."""
    _require()
    try:
        result = _db.conn.execute(
            "DELETE FROM resonance_policy WHERE policy_id = ? RETURNING policy_id",
            (policy_id,),
        )
        
        if not result.fetchall():
            raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
        
        _db.conn.commit()
        
        _safe_audit_log(
            event_type="policy_deleted",
            action="delete_resonance_policy",
            resource=policy_id,
        )
        
        return None
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to delete policy: {str(e)}")


# ══════════════════════════════════════════════════════════════════════════════
# v2.5 Enhanced: Enforcement Workflow
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/enforce/simulate", status_code=http_status.HTTP_201_CREATED)
def simulate_isolation(req: IsolationSimulationRequest):
    """
    Perform a dry-run simulation of host isolation.
    Analyzes impact without modifying the host.
    """
    _require_enforcement()
    try:
        isolation = _enforcement_engine.create_isolation_request(
            hostname=req.target_hostname,
            ip_address=req.target_ip_address,
            os_type=req.target_os,
            isolation_mode=IsolationMode[req.isolation_mode.upper()],
            isolation_trigger=IsolationTrigger.THREAT_DETECTION,
            action=IsolationAction.ISOLATE_HOST,
            requested_by="system",
            threat_severity=req.threat_severity,
            justification="Simulation requested",
        )
        
        result = _enforcement_engine.simulate_isolation(isolation.isolation_id, "system")
        
        _safe_audit_log(
            event_type="isolation_simulated",
            action="simulate_isolation",
            resource=req.target_hostname,
            details={"isolation_id": isolation.isolation_id},
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Simulation failed: {str(e)}")


@router.post("/enforce/request", status_code=http_status.HTTP_201_CREATED)
def request_isolation_approval(req: IsolationEnforcementRequest):
    """
    Request human approval for host isolation.
    Creates approval ticket in the Human Approval Gate.
    """
    _require_enforcement()
    try:
        isolation = _enforcement_engine.create_isolation_request(
            hostname=req.target_hostname,
            ip_address=req.target_ip_address,
            os_type=req.target_os,
            isolation_mode=IsolationMode[req.isolation_mode.upper()],
            isolation_trigger=IsolationTrigger.THREAT_DETECTION,
            action=IsolationAction.ISOLATE_HOST,
            requested_by=req.requested_by,
            threat_indicator=req.threat_indicator,
            threat_severity=req.threat_severity,
            mitre_technique=req.mitre_technique,
            regulatory_context=req.regulatory_context,
            justification=req.justification,
        )
        
        approval_result = _enforcement_engine.request_approval(
            isolation.isolation_id,
            req.requested_by,
            req.justification,
        )
        
        _safe_audit_log(
            event_type="approval_requested",
            action="request_isolation_approval",
            actor=req.requested_by,
            resource=req.target_hostname,
            details={
                "isolation_id": isolation.isolation_id,
                "approval_request_id": approval_result.get("approval_request_id"),
            },
        )
        
        return {
            "isolation_id": isolation.isolation_id,
            "approval_request_id": approval_result.get("approval_request_id"),
            "status": "approval_requested",
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to request approval: {str(e)}")


@router.post("/enforce/execute", status_code=http_status.HTTP_200_OK)
def execute_isolation(
    req: IsolationEnforcementRequest,
    background_tasks: BackgroundTasks,
):
    """
    Execute host isolation (post-approval).
    Enforces with HMAC-SHA256 signing and webhook dispatch.
    """
    _require_enforcement()
    try:
        isolation = _enforcement_engine.create_isolation_request(
            hostname=req.target_hostname,
            ip_address=req.target_ip_address,
            os_type=req.target_os,
            isolation_mode=IsolationMode[req.isolation_mode.upper()],
            isolation_trigger=IsolationTrigger.THREAT_DETECTION,
            action=IsolationAction.ISOLATE_HOST,
            requested_by=req.requested_by,
            threat_indicator=req.threat_indicator,
            threat_severity=req.threat_severity,
            mitre_technique=req.mitre_technique,
            regulatory_context=req.regulatory_context,
            justification=req.justification,
        )
        
        # Execute enforcement
        enforcement_result = _enforcement_engine.enforce_isolation(
            isolation.isolation_id,
            approved_by=req.requested_by,
            webhook_dispatcher=_webhook_dispatcher,
        )
        
        _safe_audit_log(
            event_type="isolation_enforced",
            action="execute_isolation",
            actor=req.requested_by,
            resource=req.target_hostname,
            result="success",
            details={
                "isolation_id": isolation.isolation_id,
                "signature": enforcement_result.get("signature"),
            },
        )
        
        return enforcement_result
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Enforcement failed: {str(e)}")


@router.post("/enforce/release", status_code=http_status.HTTP_200_OK)
def release_isolation(req: IsolationReleaseRequest):
    """Release an active isolation."""
    _require_enforcement()
    try:
        result = _enforcement_engine.release_isolation(
            req.isolation_id,
            req.released_by,
        )
        
        _safe_audit_log(
            event_type="isolation_released",
            action="release_isolation",
            actor=req.released_by,
            resource=req.isolation_id,
            result="success",
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Release failed: {str(e)}")


@router.get("/enforce/{isolation_id}/status")
def get_isolation_status(isolation_id: str):
    """Get current status of an isolation request."""
    _require_enforcement()
    status = _enforcement_engine.get_isolation_status(isolation_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Isolation {isolation_id} not found")
    return status


# ══════════════════════════════════════════════════════════════════════════════
# v2.5 Enhanced: Audit Trail
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/audit")
def get_audit_trail(
    event_type: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
):
    """
    Retrieve immutable audit trail (tamper-evident, hash-chained).
    """
    _require()
    if not AUDIT_LOGGER_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail=f"Audit logger unavailable: {_AUDIT_LOGGER_ERR}")

    events = _audit_logger.list_events(
        event_type=event_type,
        actor=actor,
        limit=limit,
        offset=offset,
    )
    
    # Verify chain integrity
    chain_status = _audit_logger.verify_chain()
    
    return {
        "count": len(events),
        "events": events,
        "chain_integrity": chain_status,
    }


@router.get("/audit/stats")
def get_audit_stats():
    """Get audit trail statistics."""
    _require()
    if not AUDIT_LOGGER_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail=f"Audit logger unavailable: {_AUDIT_LOGGER_ERR}")
    stats = _audit_logger.audit_stats()
    return stats
