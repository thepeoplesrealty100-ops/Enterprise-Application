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
  GET   /resonance/fleet                      — fleet matrix (optionally quarantined-only)
  POST  /resonance/fleet/host                 — upsert one host's posture
  GET   /resonance/settings                   — latest security-settings snapshot
  POST  /resonance/settings/snapshot          — take a fresh snapshot now
  
  // v2.5 Enhanced
  GET   /resonance/policies                   — list all isolation policies
  POST  /resonance/policies                   — create new policy
  GET   /resonance/policies/{id}              — get policy details
  PUT   /resonance/policies/{id}              — update policy
  DELETE /resonance/policies/{id}             — delete policy
  
  POST  /resonance/enforce/simulate           — dry-run isolation (impact analysis)
  POST  /resonance/enforce/request            — request approval for isolation
  POST  /resonance/enforce/execute            — execute isolation (post-approval)
  POST  /resonance/enforce/release            — release active isolation
  GET   /resonance/enforce/{id}/status        — check isolation status
  GET   /resonance/audit                      — immutable audit trail
"""

import uuid
import json
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status as http_status, BackgroundTasks
from pydantic import BaseModel

try:
    from database import DuckDBManager
    from core.enforcement import AuditedHostIsolationEngine, IsolationMode, IsolationTrigger, IsolationAction
    from core.webhook_dispatcher import WebhookDispatcher
    from core.audit_logger import AuditLogger
    _db: Optional[DuckDBManager] = DuckDBManager()
    _enforcement_engine: Optional[AuditedHostIsolationEngine] = AuditedHostIsolationEngine(_db)
    _webhook_dispatcher: Optional[WebhookDispatcher] = WebhookDispatcher(_db)
    _audit_logger: Optional[AuditLogger] = AuditLogger(_db)
    RESONANCE_OK = True
except Exception as _e:
    RESONANCE_OK = False
    _RESONANCE_ERR = str(_e)
    _db = None
    _enforcement_engine = None
    _webhook_dispatcher = None
    _audit_logger = None


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
    _audit_logger.log(
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
        
        _audit_logger.log(
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
        result = _db.conn.execute(
            """
            UPDATE resonance_policy
            SET policy_name = ?, description = ?, threat_threshold = ?,
                trigger_type = ?, isolation_mode = ?, auto_enforce = ?,
                webhook_url = ?, enabled = ?
            WHERE policy_id = ?
            RETURNING policy_id
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
        
        if not result.fetchall():
            raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
        
        _db.conn.commit()
        
        _audit_logger.log(
            event_type="policy_updated",
            action="update_resonance_policy",
            resource=policy_id,
        )
        
        return {"policy_id": policy_id, "status": "updated"}
    
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
        
        _audit_logger.log(
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
    _require()
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
        
        _audit_logger.log(
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
    _require()
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
        
        _audit_logger.log(
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
    _require()
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
        
        _audit_logger.log(
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
    _require()
    try:
        result = _enforcement_engine.release_isolation(
            req.isolation_id,
            req.released_by,
        )
        
        _audit_logger.log(
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
    _require()
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
    stats = _audit_logger.audit_stats()
    return stats
