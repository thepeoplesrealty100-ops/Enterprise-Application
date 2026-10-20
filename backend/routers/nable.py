"""
backend/routers/nable.py
=======================
Nable Network Intelligence Connector — network behavior analysis, anomaly detection,
and real-time alerting for MSP clients.

Real endpoints backed by database:
  GET  /api/nable/alerts          — Network behavior anomalies
  POST /api/nable/alerts/{id}/ack — Acknowledge alert
  POST /api/nable/alerts/{id}/resolve — Resolve with remediation
  GET  /api/nable/networks        — Monitored network segments
  POST /api/nable/webhook         — Ingest real-time alerts
  GET  /api/nable/status          — Integration health
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import json

from dependencies import get_current_user, get_db_connection
from schemas import UserSchema

router = APIRouter(prefix="/api/nable", tags=["Nable Network Intelligence"])


class NableAlert(BaseModel):
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    alert_type: str  # dns_exfil, port_scan, data_burst, c2_callback, anomalous_traffic
    source_ip: str
    dest_ip: Optional[str] = None
    dest_port: Optional[int] = None
    bytes_transferred: Optional[int] = None
    description: str
    device_name: Optional[str] = None


class AlertAckRequest(BaseModel):
    notes: str = ""


class AlertResolveRequest(BaseModel):
    remediation: str
    action_taken: str = ""


@router.get("/alerts")
async def list_nable_alerts(
    severity: Optional[str] = None,
    status: Optional[str] = Query(None, description="open, acknowledged, resolved"),
    limit: int = Query(50, ge=1, le=200),
    user: UserSchema = Depends(get_current_user),
    db = Depends(get_db_connection),
):
    """
    List network intelligence alerts from Nable integration.
    
    Returns real data from database (not simulated).
    """
    try:
        where = ["source = 'nable'"]
        params: List[Any] = []
        
        if severity:
            where.append("severity = ?")
            params.append(severity)
        
        if status:
            where.append("status = ?")
            params.append(status)
        
        where_clause = " AND ".join(where)
        
        rows = db.query(
            f"""SELECT id, severity, alert_type, source_ip, dest_ip, dest_port,
                   bytes_transferred, description, device_name, status, created_at, updated_at
               FROM network_alerts WHERE {where_clause}
               ORDER BY created_at DESC LIMIT ?""",
            tuple(params + [limit])
        )
        
        alerts = []
        for row in (rows or []):
            alerts.append({
                "alert_id": row[0],
                "severity": row[1],
                "alert_type": row[2],
                "source_ip": row[3],
                "dest_ip": row[4],
                "dest_port": row[5],
                "bytes_transferred": row[6],
                "description": row[7],
                "device_name": row[8],
                "status": row[9],
                "created_at": row[10],
                "updated_at": row[11],
            })
        
        # Count by status
        total_row = db.query("SELECT COUNT(*) FROM network_alerts WHERE source = 'nable'")
        total = total_row[0][0] if total_row else 0
        
        open_row = db.query("SELECT COUNT(*) FROM network_alerts WHERE source = 'nable' AND status = 'open'")
        open_count = open_row[0][0] if open_row else 0
        
        return {
            "ok": True,
            "alerts": alerts,
            "total": total,
            "open": open_count,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Nable alert query failed: {str(e)}")


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: str,
    req: AlertAckRequest,
    user: UserSchema = Depends(get_current_user),
    db = Depends(get_db_connection),
):
    """Acknowledge a network alert (marks as reviewed)."""
    try:
        db.execute(
            "UPDATE network_alerts SET status = 'acknowledged', acknowledged_by = ?, "
            "acknowledged_at = ?, notes = ? WHERE id = ?",
            (user.user_id, datetime.now(timezone.utc).isoformat(), req.notes, alert_id)
        )
        
        # Audit
        db.audit_log(
            user.user_id, "acknowledge_alert", "nable_network_intel", "success",
            f"Alert {alert_id} acknowledged"
        )
        
        return {
            "ok": True,
            "alert_id": alert_id,
            "status": "acknowledged",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to acknowledge alert: {str(e)}")


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    req: AlertResolveRequest,
    user: UserSchema = Depends(get_current_user),
    db = Depends(get_db_connection),
):
    """Resolve a network alert with remediation details."""
    try:
        db.execute(
            "UPDATE network_alerts SET status = 'resolved', resolved_by = ?, "
            "resolved_at = ?, remediation = ?, action_taken = ? WHERE id = ?",
            (user.user_id, datetime.now(timezone.utc).isoformat(),
             req.remediation, req.action_taken, alert_id)
        )
        
        # Log to agent logs for audit trail
        db.execute(
            "INSERT INTO agent_logs (timestamp, event, action, status, operator_id, details) "
            "VALUES (?, 'network_alert_resolved', 'nable', 'success', ?, ?)",
            (datetime.now(timezone.utc).isoformat(), user.user_id,
             json.dumps({"alert_id": alert_id, "remediation": req.remediation}))
        )
        
        # Audit
        db.audit_log(
            user.user_id, "resolve_alert", "nable_network_intel", "success",
            f"Alert {alert_id} resolved: {req.remediation}"
        )
        
        return {
            "ok": True,
            "alert_id": alert_id,
            "status": "resolved",
            "remediation": req.remediation,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve alert: {str(e)}")


@router.get("/networks")
async def list_monitored_networks(
    user: UserSchema = Depends(get_current_user),
    db = Depends(get_db_connection),
):
    """List network segments currently monitored via Nable."""
    try:
        rows = db.query(
            "SELECT id, name, cidr, location, status, created_at FROM network_segments "
            "WHERE source = 'nable' ORDER BY name"
        )
        
        networks = []
        for row in (rows or []):
            # Get alert count for this network
            alert_count = db.query(
                "SELECT COUNT(*) FROM network_alerts WHERE source = 'nable' "
                "AND source_ip LIKE ?",
                (f"{row[2].split('/')[0]}%",)
            )
            
            networks.append({
                "segment_id": row[0],
                "name": row[1],
                "cidr": row[2],
                "location": row[3],
                "status": row[4],
                "alerts_24h": alert_count[0][0] if alert_count else 0,
                "created_at": row[5],
            })
        
        return {
            "ok": True,
            "networks": networks,
            "total": len(networks),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Network list failed: {str(e)}")


@router.post("/webhook")
async def receive_nable_webhook(
    alert: NableAlert,
    db = Depends(get_db_connection),
):
    """
    Webhook endpoint for real-time Nable alert ingestion.
    
    Stores alerts in network_alerts table for real-time visibility.
    """
    try:
        alert_id = f"nable-{datetime.now(timezone.utc).timestamp()}"
        
        db.execute(
            "INSERT INTO network_alerts "
            "(id, source, severity, alert_type, source_ip, dest_ip, dest_port, "
            "bytes_transferred, description, device_name, status, created_at) "
            "VALUES (?, 'nable', ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            (alert_id, alert.severity, alert.alert_type, alert.source_ip,
             alert.dest_ip, alert.dest_port, alert.bytes_transferred,
             alert.description, alert.device_name,
             datetime.now(timezone.utc).isoformat())
        )
        
        # Log to telemetry
        db.execute(
            "INSERT INTO agent_logs (timestamp, event, action, status, operator_id, details) "
            "VALUES (?, 'network_alert_ingested', 'nable_webhook', 'success', 'webhook', ?)",
            (datetime.now(timezone.utc).isoformat(),
             json.dumps({"alert_type": alert.alert_type, "severity": alert.severity}))
        )
        
        return {
            "ok": True,
            "alert_id": alert_id,
            "status": "ingested",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook ingestion failed: {str(e)}")


@router.get("/status")
async def nable_integration_status(
    user: UserSchema = Depends(get_current_user),
    db = Depends(get_db_connection),
):
    """Check Nable integration health and sync status."""
    try:
        # Get last alert received
        last_alert = db.query(
            "SELECT MAX(created_at) FROM network_alerts WHERE source = 'nable'"
        )
        last_sync = last_alert[0][0] if (last_alert and last_alert[0][0]) else None
        
        # Count open alerts
        open_alerts = db.query(
            "SELECT COUNT(*) FROM network_alerts WHERE source = 'nable' AND status = 'open'"
        )
        open_count = open_alerts[0][0] if open_alerts else 0
        
        # Count networks
        networks = db.query(
            "SELECT COUNT(*) FROM network_segments WHERE source = 'nable'"
        )
        network_count = networks[0][0] if networks else 0
        
        return {
            "ok": True,
            "status": "connected",
            "last_sync": last_sync or datetime.now(timezone.utc).isoformat(),
            "open_alerts": open_count,
            "monitored_networks": network_count,
            "webhook_url": "/api/nable/webhook",
            "health": "healthy" if open_count < 100 else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")
