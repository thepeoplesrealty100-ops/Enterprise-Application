"""
backend/routers/ui_bridge.py

UI Bridge Router — Connects the static frontend to live backend data.
Provides REST endpoints that map to dashboard components (fleet, matrix, settings, etc.)

Endpoints:
  - GET  /api/dashboard/fleet              — Device/user fleet with filtering
  - GET  /api/dashboard/fleet/{id}         — Single device details
  - POST /api/dashboard/fleet/{id}/action  — Device action (isolate, scan, etc.)
  - GET  /api/dashboard/matrix             — Threat matrix data (global predictive)
  - GET  /api/dashboard/settings           — Global settings snapshot
  - GET  /api/dashboard/fabric/status      — Unified Security Fabric posture (dashboard-shaped)
  - GET  /api/dashboard/scripts/catalog    — Script library catalog (paginated, dashboard-shaped)
  - GET  /api/dashboard/resonance/policies — Automation policies (dashboard-shaped)
  - GET  /api/dashboard/resonance/audit    — Recent agent_logs activity (dashboard-shaped)
  - GET  /api/health/detailed              — Detailed system health

  RECONCILIATION NOTE: the four /dashboard/{fabric/status, scripts/catalog,
  resonance/policies, resonance/audit} routes were originally defined
  WITHOUT the /dashboard prefix (i.e. at /api/fabric/status,
  /api/scripts/catalog, /api/resonance/policies, /api/resonance/audit) --
  exact path collisions with routers/fabric.py, routers/scripts.py, and
  routers/resonance.py, which are registered earlier in app.py and would
  have silently won every request, making these four endpoints
  unreachable dead code. Worse: this branch's own frontend (integration.js)
  and this Phase-2 frontend (frontend/js/api-client.js) both call some of
  those same paths expecting DIFFERENT response shapes from DIFFERENT
  backend implementations (e.g. fabric.py's /status returns
  security_agents' native FabricEngine.status() shape; this router's
  fabric endpoint returns a different, dashboard-flattened shape) -- so
  reordering router registration to let one win would have silently broken
  the other frontend instead. Renamed under /dashboard/ so both coexist;
  frontend/js/api-client.js was updated to match. Separately: this
  router's /resonance/audit reads agent_logs (generic telemetry), NOT the
  tamper-evident, hash-chained resonance_audit_trail table
  core/audit_logger.py maintains -- it is a different, weaker view under a
  similar name, not a duplicate of the real audit trail exposed at
  GET /api/resonance/audit (routers/resonance.py).

v1.0 - Fully integrated with DuckDB, SSE telemetry, and approval gates
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import json
from typing import Optional
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui-bridge"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class DeviceFiltersRequest(BaseModel):
    client: Optional[str] = None
    status: Optional[str] = None
    risk_level: Optional[str] = None
    page: int = 1
    per_page: int = 20


class DeviceActionRequest(BaseModel):
    action: str  # "scan", "isolate", "reset_pass", "quarantine", "release"
    reason: Optional[str] = None
    operator_id: str = "system"
    duration_minutes: Optional[int] = None


class PolicyRequest(BaseModel):
    policy_name: str
    description: Optional[str] = None
    threat_threshold: float = 0.7
    trigger_type: str = "threat_detection"
    isolation_mode: str = "network_only"
    auto_enforce: bool = False
    webhook_url: Optional[str] = None
    enabled: bool = True


# ============================================================================
# DEVICE FLEET ENDPOINTS
# ============================================================================

@router.get("/dashboard/fleet")
async def get_device_fleet(
    client: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """
    Get global device & user fleet with filtering.
    Returns paginated device list with current status, risk level, last seen, etc.
    """
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        # Build query
        where_parts = []
        params = []
        
        if client:
            where_parts.append("pentest_id IN (SELECT id FROM pentest_runs WHERE client_name = ?)")
            params.append(client)
        
        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        offset = (page - 1) * per_page
        
        # Query devices from network_map table
        rows = db.query(
            f"""
            SELECT id, hostname, ip_address, os_fingerprint, mac_address, 
                   risk_score, tags, discovered_at
            FROM network_map
            WHERE {where_clause}
            ORDER BY discovered_at DESC LIMIT ? OFFSET ?
            """,
            params + [per_page, offset]
        )
        
        # Get count
        count_rows = db.query(
            f"SELECT COUNT(*) FROM network_map WHERE {where_clause}",
            params
        )
        total = count_rows[0][0] if count_rows else 0
        
        devices = []
        for row in (rows or []):
            devices.append({
                "id": row[0],
                "name": row[1] or "Unknown",
                "ip": row[2],
                "os": row[3],
                "mac": row[4],
                "risk": float(row[5] or 0),
                "tags": json.loads(row[6]) if row[6] else [],
                "discovered": row[7],
            })
        
        return {
            "data": devices,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
        }
    except Exception as e:
        logger.error(f"Error fetching device fleet: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/fleet/{device_id}")
async def get_device_details(device_id: int):
    """Get detailed information for a single device."""
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        rows = db.query(
            """
            SELECT id, hostname, ip_address, os_fingerprint, mac_address, 
                   risk_score, tags, discovered_at, notes
            FROM network_map WHERE id = ?
            """,
            (device_id,)
        )
        
        if not rows:
            raise HTTPException(status_code=404, detail="Device not found")
        
        row = rows[0]
        return {
            "id": row[0],
            "name": row[1] or "Unknown",
            "ip": row[2],
            "os": row[3],
            "mac": row[4],
            "risk": float(row[5] or 0),
            "tags": json.loads(row[6]) if row[6] else [],
            "discovered": row[7],
            "notes": row[8],
        }
    except Exception as e:
        logger.error(f"Error fetching device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dashboard/fleet/{device_id}/action")
async def execute_device_action(device_id: int, request: DeviceActionRequest):
    """
    Execute an action on a device (isolate, scan, reset password, quarantine, release).
    Logs action to audit trail and returns confirmation.
    """
    from database import get_db_manager
    db = get_db_manager()
    
    # Validate action
    valid_actions = ["scan", "isolate", "reset_pass", "quarantine", "release"]
    if request.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")
    
    try:
        # Log the action to agent_logs
        event_id = str(uuid.uuid4())
        db.conn.execute(
            """
            INSERT INTO agent_logs (timestamp, event, action, status, operator_id, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                "DEVICE_ACTION",
                request.action,
                "initiated",
                request.operator_id,
                json.dumps({
                    "device_id": device_id,
                    "reason": request.reason,
                    "duration_minutes": request.duration_minutes
                })
            )
        )
        db.conn.commit()
        
        return {
            "status": "success",
            "device_id": device_id,
            "action": request.action,
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error executing device action: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GLOBAL MATRIX ENDPOINTS
# ============================================================================

@router.get("/dashboard/matrix")
async def get_global_matrix(time_window_minutes: int = Query(60, ge=5, le=1440)):
    """
    Get global predictive threat matrix data.
    Returns threat events with severity and distribution.
    """
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        cutoff_time = (datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)).isoformat()
        
        # Query recent threat findings. findings has no numeric CVSS column
        # (RECONCILIATION FIX: this query originally selected a
        # `cvss_score` column that doesn't exist in the real findings
        # schema -- database.py's CREATE TABLE only has id/pentest_id/
        # severity/title/description/attack_technique/remediation/
        # created_at -- raising a live Binder Error on every call. Severity
        # is the only real risk signal on this table, so `score` below is
        # derived from it rather than read from a nonexistent column.)
        rows = db.query(
            """
            SELECT id, title, severity, created_at
            FROM findings
            WHERE created_at > ? AND severity IN ('CRITICAL', 'HIGH')
            ORDER BY created_at DESC LIMIT 100
            """,
            (cutoff_time,)
        )

        # Group by severity for matrix
        threats_by_severity = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
        severity_score = {"CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.5, "LOW": 0.25}

        for row in (rows or []):
            threat = {
                "id": row[0],
                "title": row[1],
                "severity": row[2],
                "score": severity_score.get(row[2], 0.0),
                "timestamp": row[3],
            }
            if row[2] in threats_by_severity:
                threats_by_severity[row[2]].append(threat)
        
        return {
            "matrix": threats_by_severity,
            "time_window_minutes": time_window_minutes,
            "total_threats": sum(len(v) for v in threats_by_severity.values()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error fetching global matrix: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DASHBOARD SETTINGS ENDPOINTS
# ============================================================================

@router.get("/dashboard/settings")
async def get_global_settings():
    """Get global settings snapshot."""
    try:
        # Return default settings
        return {
            "settings": {
                "api_encryption": "ML-DSA-65 + AES-256-GCM",
                "quantum_backend": "Qiskit-Aer",
                "audit_enabled": True,
                "approval_gate_enabled": True,
                "auto_isolation": False,
                "threat_threshold": 0.7,
            }
        }
    except Exception as e:
        logger.error(f"Error fetching global settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# UNIFIED SECURITY FABRIC ENDPOINTS
# ============================================================================

@router.get("/dashboard/fabric/status")
async def get_fabric_status():
    """
    Get unified security fabric posture (7-pillar NSA/CISA Zero Trust model).
    Returns overall score, maturity level, and per-pillar breakdown.
    """
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        # Query fabric modules
        rows = db.query(
            """
            SELECT module_key, label, pillar, maturity, status
            FROM fabric_modules
            ORDER BY pillar
            """
        )
        
        # Build fabric response
        pillars = {}
        for row in (rows or []):
            pillar = row[2]
            if pillar not in pillars:
                pillars[pillar] = {
                    "name": pillar,
                    "capabilities": [],
                    "scores": [],
                }
            
            # Map maturity to score
            maturity_score = {"Traditional": 25, "Initial": 50, "Advanced": 75, "Optimal": 100}
            score = maturity_score.get(row[3], 50)
            
            pillars[pillar]["capabilities"].append({
                "id": row[0],
                "name": row[1],
                "maturity": row[3],
                "status": row[4],
            })
            pillars[pillar]["scores"].append(score)
        
        # Calculate overall
        all_scores = [s for pillar in pillars.values() for s in pillar["scores"]]
        overall_score = sum(all_scores) / len(all_scores) if all_scores else 0
        
        # Calculate per-pillar averages
        for pillar in pillars:
            scores = pillars[pillar]["scores"]
            pillars[pillar]["average_score"] = sum(scores) / len(scores) if scores else 0
            del pillars[pillar]["scores"]
        
        def score_to_level(score):
            if score >= 85:
                return "Optimal"
            elif score >= 70:
                return "Advanced"
            elif score >= 50:
                return "Initial"
            else:
                return "Traditional"
        
        return {
            "fabric": "Unified Security Fabric",
            "overall_score": round(overall_score, 1),
            "overall_level": score_to_level(overall_score),
            "capability_count": len(rows or []),
            "by_pillar": {
                name: {
                    "score": round(data["average_score"], 1),
                    "level": score_to_level(data["average_score"]),
                    "capabilities": data["capabilities"],
                }
                for name, data in pillars.items()
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error fetching fabric status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SCRIPT CATALOG ENDPOINTS
# ============================================================================

@router.get("/dashboard/scripts/catalog")
async def get_script_catalog(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Get script library catalog with filtering."""
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        rows = db.query(
            """
            SELECT id, name, description, category, language, version
            FROM script_library
            LIMIT ? OFFSET ?
            """,
            (per_page, (page - 1) * per_page)
        )
        
        count_rows = db.query("SELECT COUNT(*) FROM script_library")
        total = count_rows[0][0] if count_rows else 0
        
        scripts = []
        for row in (rows or []):
            scripts.append({
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "category": row[3],
                "language": row[4],
                "version": row[5],
            })
        
        return {
            "data": scripts,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
        }
    except Exception as e:
        logger.error(f"Error fetching script catalog: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RESONANCE POLICY ENDPOINTS
# ============================================================================

@router.get("/dashboard/resonance/policies")
async def get_resonance_policies():
    """Get all automation policies."""
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        rows = db.query(
            """
            SELECT id, policy_id, policy_name, description, threat_threshold,
                   trigger_type, isolation_mode, auto_enforce, enabled, created_at
            FROM resonance_policy
            ORDER BY created_at DESC
            """
        )
        
        policies = []
        for row in (rows or []):
            policies.append({
                "id": row[0],
                "policy_id": row[1],
                "name": row[2],
                "description": row[3],
                "threat_threshold": float(row[4] or 0),
                "trigger_type": row[5],
                "isolation_mode": row[6],
                "auto_enforce": bool(row[7]),
                "enabled": bool(row[8]),
                "created_at": row[9],
            })
        
        return {"policies": policies}
    except Exception as e:
        logger.error(f"Error fetching resonance policies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dashboard/resonance/policies")
async def create_resonance_policy(request: PolicyRequest):
    """Create a new automation policy."""
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        policy_id = f"POL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        db.conn.execute(
            """
            INSERT INTO resonance_policy 
            (policy_id, policy_name, description, threat_threshold, trigger_type,
             isolation_mode, auto_enforce, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy_id, request.policy_name, request.description,
                request.threat_threshold, request.trigger_type,
                request.isolation_mode, request.auto_enforce, request.enabled,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            )
        )
        db.conn.commit()
        
        return {
            "status": "success",
            "policy_id": policy_id,
            "name": request.policy_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error creating policy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# AUDIT TRAIL ENDPOINTS
# ============================================================================

@router.get("/dashboard/resonance/audit")
async def get_resonance_audit(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = Query(None),
):
    """Get immutable audit trail with optional filtering."""
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        rows = db.query(
            """
            SELECT id, timestamp, event, action, status, operator_id, details
            FROM agent_logs
            ORDER BY timestamp DESC LIMIT ? OFFSET ?
            """,
            (limit, offset)
        )
        
        audit_trail = []
        for row in (rows or []):
            audit_trail.append({
                "id": row[0],
                "timestamp": row[1],
                "event_type": row[2],
                "action": row[3],
                "status": row[4],
                "actor": row[5],
                "details": json.loads(row[6]) if row[6] else {},
            })
        
        return {
            "audit_trail": audit_trail,
            "count": len(audit_trail),
        }
    except Exception as e:
        logger.error(f"Error fetching audit trail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HEALTH & METRICS ENDPOINTS
# ============================================================================

@router.get("/health/detailed")
async def get_detailed_health():
    """Get detailed system health with component status."""
    from database import get_db_manager
    db = get_db_manager()
    
    try:
        # Check database connectivity
        db_result = db.query("SELECT 1")
        db_status = "healthy" if db_result else "unhealthy"
        
        # Get resource counts
        try:
            devices = db.query("SELECT COUNT(*) FROM network_map")[0][0]
            findings = db.query("SELECT COUNT(*) FROM findings")[0][0]
            policies = db.query("SELECT COUNT(*) FROM resonance_policy")[0][0]
            logs = db.query("SELECT COUNT(*) FROM agent_logs")[0][0]
        except:
            devices = findings = policies = logs = 0
        
        return {
            "status": "operational" if db_status == "healthy" else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "database": {
                    "status": db_status,
                    "type": "DuckDB",
                },
                "resources": {
                    "devices": devices,
                    "findings": findings,
                    "policies": policies,
                    "audit_logs": logs,
                },
            },
        }
    except Exception as e:
        logger.error(f"Error in detailed health check: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
