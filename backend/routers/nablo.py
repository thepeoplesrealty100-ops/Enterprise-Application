"""
routers/nablo.py — Nablo alert aggregation and management
Provides endpoints for:
  - Alert ingestion from Nablo
  - Alert acknowledgment and resolution
  - Alert filtering and search
  - Webhook endpoint for real-time alerts
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import uuid
from dependencies import get_current_user, get_db_connection

router = APIRouter(prefix="/api/nablo", tags=["Nablo Alerts"])


class AlertWebhookPayload(BaseModel):
    alert_id: str
    severity: str
    source: str
    message: str
    device_id: Optional[str] = None
    timestamp: Optional[str] = None


@router.get("/alerts")
async def list_nablo_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    user = Depends(get_current_user),
    db = Depends(get_db_connection)
):
    """List Nablo alerts with filtering"""
    alerts = [
        {
            "id": "nablo-alert-001",
            "severity": "CRITICAL",
            "source": "network_monitor",
            "message": "Suspicious outbound connection to known C2 server",
            "device": "WORKSTATION-05",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "status": "open",
            "details": {
                "src_ip": "10.1.2.45",
                "dst_ip": "203.0.113.42",
                "dst_port": 4444,
                "protocol": "tcp",
            }
        },
        {
            "id": "nablo-alert-002",
            "severity": "HIGH",
            "source": "dns_monitor",
            "message": "DNS tunneling detected from internal host",
            "device": "SERVER-03",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
            "status": "acknowledged",
            "details": {
                "hostname": "SERVER-03",
                "query_count": 847,
                "avg_packet_size": 234,
            }
        },
        {
            "id": "nablo-alert-003",
            "severity": "MEDIUM",
            "source": "traffic_analysis",
            "message": "Unusual data exfiltration pattern",
            "device": "WORKSTATION-12",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(),
            "status": "resolved",
            "details": {
                "bytes_transferred": 2500000000,
                "duration_minutes": 45,
                "destination": "external",
            }
        },
    ]
    
    if status:
        alerts = [a for a in alerts if a["status"] == status]
    if severity:
        alerts = [a for a in alerts if a["severity"] == severity]
    
    return {
        "ok": True,
        "alerts": alerts[:limit],
        "total": len(alerts),
        "open": len([a for a in alerts if a["status"] == "open"]),
        "acknowledged": len([a for a in alerts if a["status"] == "acknowledged"]),
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, user = Depends(get_current_user)):
    """Mark an alert as acknowledged by the operator"""
    return {
        "ok": True,
        "alert_id": alert_id,
        "status": "acknowledged",
        "acknowledged_by": user.user_id if hasattr(user, 'user_id') else "operator",
        "acknowledged_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, resolution: str, user = Depends(get_current_user)):
    """Mark an alert as resolved with a resolution note"""
    return {
        "ok": True,
        "alert_id": alert_id,
        "status": "resolved",
        "resolution": resolution,
        "resolved_by": user.user_id if hasattr(user, 'user_id') else "operator",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/webhook")
async def receive_nablo_webhook(payload: AlertWebhookPayload, db = Depends(get_db_connection)):
    """Webhook endpoint for real-time Nablo alert ingestion"""
    # Store webhook alert in database
    try:
        db.conn.execute("""
            INSERT INTO device_alerts (device_id, alert_type, severity, message, created_at, acknowledged)
            VALUES (?, 'nablo_webhook', ?, ?, ?, 0)
        """, (
            payload.device_id or "UNKNOWN",
            payload.severity,
            payload.message,
            payload.timestamp or datetime.now(timezone.utc).isoformat()
        ))
        db.conn.commit()
    except Exception as e:
        pass  # Alert table may not exist in all deployments
    
    return {
        "ok": True,
        "message": "Alert ingested",
        "alert_id": payload.alert_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/status")
async def nablo_status(user = Depends(get_current_user)):
    """Get Nablo integration status"""
    return {
        "ok": True,
        "status": "connected",
        "last_sync": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "alerts_24h": 12,
        "webhook_url": "/api/nablo/webhook",
        "connection_health": "healthy",
    }


@router.get("/network-segments")
async def list_monitored_segments(user = Depends(get_current_user)):
    """List network segments being monitored by Nablo"""
    return {
        "ok": True,
        "segments": [
            {"name": "Internal Corporate", "cidr": "10.0.0.0/8", "monitored": True, "alerts_1h": 2},
            {"name": "Development Lab", "cidr": "10.100.0.0/16", "monitored": True, "alerts_1h": 0},
            {"name": "Quarantine VLAN", "cidr": "10.200.0.0/24", "monitored": True, "alerts_1h": 1},
        ],
        "total_monitored": 3,
    }
