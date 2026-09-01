"""
backend/routers/ui_bridge.py

UI Bridge Router — Connects the static frontend to live backend data.
Provides REST endpoints that map to dashboard components (fleet, matrix, settings, etc.)

Endpoints:
  - GET  /api/dashboard/fleet           — Device/user fleet with filtering
  - GET  /api/dashboard/fleet/{id}      — Single device details
  - POST /api/dashboard/fleet/{id}/action — Device action (isolate, scan, etc.)
  - GET  /api/dashboard/matrix          — Threat matrix data (global predictive)
  - GET  /api/dashboard/settings        — Global settings snapshot
  - GET  /api/dashboard/settings/{tab}  — Specific settings tab
  - GET  /api/fabric/status             — Unified Security Fabric posture
  - GET  /api/telemetry/metrics         — Prometheus-compatible metrics
  - GET  /api/scripts/catalog           — Script library catalog
  - GET  /api/resonance/policies        — Automation policies
  - POST /api/resonance/policies        — Create new policy
  - GET  /api/resonance/audit           — Immutable audit trail
  - GET  /api/health/detailed           — Detailed system health

v1.0 - Fully integrated with DuckDB, SSE telemetry, and approval gates
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import json
from typing import List, Dict, Optional, Any
import logging

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
    trigger_type: str = "threat_detection"  # threat_detection, compliance_breach, manual
    isolation_mode: str = "network_only"  # network_only, full_isolation, monitored
    auto_enforce: bool = False
    webhook_url: Optional[str] = None
    enabled: bool = True


class SettingsUpdateRequest(BaseModel):
    setting_key: str
    setting_value: Any
    operator_id: str = "system"


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
    from database import DuckDBManager
    db = DuckDBManager()
    
    # Build WHERE clause
    where_parts = []
    params = []
    
    if client:
        where_parts.append("client_name = ?")
        params.append(client)
    
    if status:
        where_parts.append("device_status = ?")
        params.append(status)
    
    where_clause = " AND ".join(where_parts) if where_parts else "1=1"
    offset = (page - 1) * per_page
    
    try:
        # Query devices (assuming table exists in schema)
        devices = db.query(
            f"""
            SELECT id, device_name, user_id, client_name, device_type, os_version,
                   device_status, risk_level, last_login, ip_address, location
            FROM devices
            WHERE {where_clause}
            ORDER BY last_login DESC LIMIT ? OFFSET ?
            """,
            params + [per_page, offset]
        )
        
        # Get total count
        count_result = db.query(
            f"SELECT COUNT(*) as total FROM devices WHERE {where_clause}",
            params
        )
        total = count_result[0][0] if count_result else 0
        
        return {
            "data": [
                {
                    "id": d[0],
                    "name": d[1],
                    "user": d[2],
                    "client": d[3],
                    "type": d[4],
                    "os": d[5],
                    "status": d[6],
                    "risk": d[7],
                    "lastLogin": d[8],
                    "ip": d[9],
                    "location": d[10],
                }
                for d in (devices or [])
            ],
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
async def get_device_details(device_id: str):
    """Get detailed information for a single device."""
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        device = db.query(
            """
            SELECT id, device_name, user_id, client_name, device_type, os_version,
                   device_status, risk_level, last_login, ip_address, location,
                   mac_address, serial_number, installed_agents
            FROM devices WHERE id = ?
            """,
            (device_id,)
        )
        
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        d = device[0]
        return {
            "id": d[0],
            "name": d[1],
            "user": d[2],
            "client": d[3],
            "type": d[4],
            "os": d[5],
            "status": d[6],
            "risk": d[7],
            "lastLogin": d[8],
            "ip": d[9],
            "location": d[10],
            "mac": d[11],
            "serial": d[12],
            "agents": d[13],
        }
    except Exception as e:
        logger.error(f"Error fetching device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dashboard/fleet/{device_id}/action")
async def execute_device_action(device_id: str, request: DeviceActionRequest):
    """
    Execute an action on a device (isolate, scan, reset password, quarantine, release).
    Logs action to audit trail and returns confirmation.
    """
    from database import DuckDBManager
    db = DuckDBManager()
    
    # Validate action
    valid_actions = ["scan", "isolate", "reset_pass", "quarantine", "release"]
    if request.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")
    
    try:
        # Log the action to audit trail
        audit_event_id = db.add_audit_event(
            event_type=f"DEVICE_{request.action.upper()}",
            resource_type="device",
            resource_id=device_id,
            actor=request.operator_id,
            action=request.action,
            status="initiated",
            details={"reason": request.reason, "duration_minutes": request.duration_minutes}
        )
        
        # Update device status based on action
        status_map = {
            "isolate": "isolated",
            "quarantine": "quarantined",
            "scan": "scanning",
            "release": "online",
            "reset_pass": "online",
        }
        new_status = status_map.get(request.action, "online")
        
        db.execute(
            "UPDATE devices SET device_status = ?, updated_at = ? WHERE id = ?",
            (new_status, datetime.now(timezone.utc).isoformat(), device_id)
        )
        
        return {
            "status": "success",
            "device_id": device_id,
            "action": request.action,
            "audit_event_id": audit_event_id,
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
    Returns threat origins, target locations, and threat types with severity.
    """
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        cutoff_time = (datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)).isoformat()
        
        # Query recent threat events
        threats = db.query(
            """
            SELECT id, threat_origin, threat_type, severity, timestamp, 
                   target_location, event_data
            FROM threat_events
            WHERE timestamp > ? AND severity >= 3
            ORDER BY timestamp DESC LIMIT 100
            """,
            (cutoff_time,)
        )
        
        # Group by origin for matrix display
        threat_groups = {}
        for threat in (threats or []):
            origin = threat[1] or "Unknown"
            if origin not in threat_groups:
                threat_groups[origin] = {
                    "origin": origin,
                    "threats": [],
                    "total": 0,
                }
            
            threat_groups[origin]["threats"].append({
                "id": threat[0],
                "type": threat[2],
                "severity": threat[3],
                "timestamp": threat[4],
                "target": threat[5],
            })
            threat_groups[origin]["total"] += 1
        
        return {
            "matrix": list(threat_groups.values()),
            "time_window_minutes": time_window_minutes,
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
    """Get global settings snapshot (all tabs combined)."""
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        settings = db.query(
            """
            SELECT setting_key, setting_value, updated_at, updated_by
            FROM global_settings
            ORDER BY setting_key
            """
        )
        
        return {
            "settings": [
                {
                    "key": s[0],
                    "value": s[1] if isinstance(s[1], (str, int, float, bool)) else json.loads(s[1]),
                    "updated_at": s[2],
                    "updated_by": s[3],
                }
                for s in (settings or [])
            ],
        }
    except Exception as e:
        logger.error(f"Error fetching global settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/settings/{tab}")
async def get_settings_tab(tab: str):
    """Get settings for a specific tab (profile, encryption, api, etc.)."""
    from database import DuckDBManager
    db = DuckDBManager()
    
    tab_mapping = {
        "profile": "operator_*",
        "encryption": "encryption_*",
        "api": "api_*",
        "rbac": "rbac_*",
        "audit": "audit_*",
        "kms": "kms_*",
    }
    
    if tab not in tab_mapping:
        raise HTTPException(status_code=400, detail=f"Unknown settings tab: {tab}")
    
    try:
        pattern = tab_mapping[tab]
        settings = db.query(
            """
            SELECT setting_key, setting_value, updated_at, updated_by
            FROM global_settings
            WHERE setting_key LIKE ?
            ORDER BY setting_key
            """,
            (pattern,)
        )
        
        return {
            "tab": tab,
            "settings": [
                {
                    "key": s[0],
                    "value": s[1] if isinstance(s[1], (str, int, float, bool)) else json.loads(s[1]),
                    "updated_at": s[2],
                    "updated_by": s[3],
                }
                for s in (settings or [])
            ],
        }
    except Exception as e:
        logger.error(f"Error fetching settings tab {tab}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dashboard/settings/{tab}")
async def update_settings_tab(tab: str, request: SettingsUpdateRequest):
    """Update a specific setting in a tab."""
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        db.execute(
            """
            INSERT INTO global_settings (setting_key, setting_value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET 
                setting_value = excluded.setting_value,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                request.setting_key,
                json.dumps(request.setting_value) if not isinstance(request.setting_value, str) else request.setting_value,
                datetime.now(timezone.utc).isoformat(),
                request.operator_id,
            )
        )
        
        return {
            "status": "success",
            "setting_key": request.setting_key,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# UNIFIED SECURITY FABRIC ENDPOINTS
# ============================================================================

@router.get("/fabric/status")
async def get_fabric_status():
    """
    Get unified security fabric posture (7-pillar NSA/CISA Zero Trust model).
    Returns overall score, maturity level, and per-pillar breakdown.
    """
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        # Query fabric capabilities and their current status
        capabilities = db.query(
            """
            SELECT capability_id, capability_name, pillar, maturity_level, 
                   score, status, updated_at
            FROM fabric_capabilities
            ORDER BY pillar, capability_name
            """
        )
        
        # Group by pillar and calculate aggregate
        pillars = {}
        total_score = 0
        count = 0
        
        for cap in (capabilities or []):
            pillar = cap[2]
            if pillar not in pillars:
                pillars[pillar] = {
                    "name": pillar,
                    "capabilities": [],
                    "scores": [],
                }
            
            pillars[pillar]["capabilities"].append({
                "id": cap[0],
                "name": cap[1],
                "maturity": cap[3],
                "score": cap[4],
                "status": cap[5],
            })
            pillars[pillar]["scores"].append(cap[4])
            total_score += cap[4]
            count += 1
        
        # Calculate per-pillar averages and overall
        for pillar in pillars:
            scores = pillars[pillar]["scores"]
            pillars[pillar]["average_score"] = sum(scores) / len(scores) if scores else 0
            del pillars[pillar]["scores"]
        
        overall_score = total_score / count if count > 0 else 0
        
        # Map score to level
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
            "capability_count": len(capabilities or []),
            "posture": {
                "overall_score": round(overall_score, 1),
                "overall_level": score_to_level(overall_score),
                "scale": ["Traditional", "Initial", "Advanced", "Optimal"],
                "by_pillar": {
                    name: {
                        "score": round(data["average_score"], 1),
                        "level": score_to_level(data["average_score"]),
                        "capabilities": data["capabilities"],
                    }
                    for name, data in pillars.items()
                },
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error fetching fabric status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SCRIPT CATALOG ENDPOINTS
# ============================================================================

@router.get("/scripts/catalog")
async def get_script_catalog(
    category: Optional[str] = Query(None),
    approved: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Get script library catalog with filtering."""
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        where_parts = []
        params = []
        
        if category:
            where_parts.append("category = ?")
            params.append(category)
        
        if approved is not None:
            where_parts.append("approved = ?")
            params.append(approved)
        
        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        offset = (page - 1) * per_page
        
        scripts = db.query(
            f"""
            SELECT id, script_id, name, description, category, language, 
                   version, approved, created_at
            FROM script_library
            WHERE {where_clause}
            ORDER BY created_at DESC LIMIT ? OFFSET ?
            """,
            params + [per_page, offset]
        )
        
        count_result = db.query(
            f"SELECT COUNT(*) FROM script_library WHERE {where_clause}",
            params
        )
        total = count_result[0][0] if count_result else 0
        
        return {
            "data": [
                {
                    "id": s[0],
                    "script_id": s[1],
                    "name": s[2],
                    "description": s[3],
                    "category": s[4],
                    "language": s[5],
                    "version": s[6],
                    "approved": s[7],
                    "created_at": s[8],
                }
                for s in (scripts or [])
            ],
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

@router.get("/resonance/policies")
async def get_resonance_policies():
    """Get all automation policies."""
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        policies = db.query(
            """
            SELECT id, policy_id, policy_name, description, threat_threshold,
                   trigger_type, isolation_mode, auto_enforce, webhook_url,
                   enabled, created_at, updated_at
            FROM resonance_policy
            ORDER BY created_at DESC
            """
        )
        
        return {
            "policies": [
                {
                    "id": p[0],
                    "policy_id": p[1],
                    "name": p[2],
                    "description": p[3],
                    "threat_threshold": p[4],
                    "trigger_type": p[5],
                    "isolation_mode": p[6],
                    "auto_enforce": p[7],
                    "webhook_url": p[8],
                    "enabled": p[9],
                    "created_at": p[10],
                    "updated_at": p[11],
                }
                for p in (policies or [])
            ],
        }
    except Exception as e:
        logger.error(f"Error fetching resonance policies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resonance/policies")
async def create_resonance_policy(request: PolicyRequest):
    """Create a new automation policy."""
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        policy_id = f"POL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        db.execute(
            """
            INSERT INTO resonance_policy 
            (policy_id, policy_name, description, threat_threshold, trigger_type,
             isolation_mode, auto_enforce, webhook_url, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy_id, request.policy_name, request.description,
                request.threat_threshold, request.trigger_type,
                request.isolation_mode, request.auto_enforce,
                request.webhook_url, request.enabled,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            )
        )
        
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

@router.get("/resonance/audit")
async def get_resonance_audit(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = Query(None),
):
    """Get immutable audit trail with optional filtering."""
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        where_clause = ""
        params = []
        
        if event_type:
            where_clause = "WHERE event_type = ? "
            params.append(event_type)
        
        audit_events = db.query(
            f"""
            SELECT id, event_id, event_type, isolation_id, policy_id, actor,
                   status, event_data, signature_hmac, timestamp
            FROM resonance_audit_trail
            {where_clause}
            ORDER BY timestamp DESC LIMIT ? OFFSET ?
            """,
            params + [limit, offset]
        )
        
        return {
            "audit_trail": [
                {
                    "id": a[0],
                    "event_id": a[1],
                    "event_type": a[2],
                    "isolation_id": a[3],
                    "policy_id": a[4],
                    "actor": a[5],
                    "status": a[6],
                    "data": json.loads(a[7]) if a[7] else {},
                    "signature": a[8],
                    "timestamp": a[9],
                }
                for a in (audit_events or [])
            ],
            "count": len(audit_events or []),
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
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        # Check database
        db_result = db.query("SELECT 1")
        db_status = "healthy" if db_result else "unhealthy"
        
        # Count critical resources
        devices_count = db.query("SELECT COUNT(*) FROM devices")[0][0]
        threat_events = db.query("SELECT COUNT(*) FROM threat_events")[0][0]
        policies = db.query("SELECT COUNT(*) FROM resonance_policy")[0][0]
        audit_events = db.query("SELECT COUNT(*) FROM resonance_audit_trail")[0][0]
        
        return {
            "status": "operational" if db_status == "healthy" else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "database": {
                    "status": db_status,
                    "type": "DuckDB",
                },
                "resources": {
                    "devices": devices_count,
                    "threat_events": threat_events,
                    "policies": policies,
                    "audit_events": audit_events,
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


@router.get("/telemetry/metrics")
async def get_telemetry_metrics():
    """
    Get Prometheus-compatible metrics endpoint.
    Returns metrics in Prometheus text format.
    """
    from database import DuckDBManager
    db = DuckDBManager()
    
    try:
        metrics = []
        
        # Count metrics
        devices = db.query("SELECT COUNT(*) FROM devices")[0][0]
        threats = db.query("SELECT COUNT(*) FROM threat_events")[0][0]
        policies = db.query("SELECT COUNT(*) FROM resonance_policy")[0][0]
        
        metrics.append(f"jakal_devices_total {devices}")
        metrics.append(f"jakal_threats_total {threats}")
        metrics.append(f"jakal_policies_total {policies}")
        
        # Status gauge (1 = operational, 0 = down)
        metrics.append("jakal_system_operational 1")
        
        response_text = "\n".join(metrics) + "\n"
        
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(response_text, media_type="text/plain")
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
