"""
backend/routers/nable.py
========================
N-able network-intelligence connector: ingest network-behaviour alerts
(webhook), list / acknowledge / resolve them, and report integration health.

Endpoints (all under /api/nable):
  GET  /alerts                  list alerts (filter: severity, state)
  POST /alerts/{id}/ack         acknowledge an alert
  POST /alerts/{id}/resolve     resolve with remediation notes
  GET  /networks                monitored network segments (+ alert counts)
  POST /networks                register a monitored segment
  POST /webhook                 ingest an alert from N-able
  GET  /status                  integration health

Storage: two DuckDB tables owned by this module (network_alerts,
network_segments), created on first use. Nothing is simulated: an empty
install returns empty lists and ``connected: false`` until a webhook has
actually delivered something.

Webhook auth: if NABLE_WEBHOOK_SECRET is set, the caller must send it in the
``X-Nable-Secret`` header (constant-time compare). If it is NOT set, the
webhook requires a normal authenticated user -- it is never open.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dependencies import get_authenticated_user, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nable", tags=["N-able Network Intelligence"])

try:
    from database import get_db_manager
    _db = get_db_manager()
    NABLE_OK = True
    _ERR: Optional[str] = None
except Exception as _e:  # noqa: BLE001
    NABLE_OK = False
    _ERR = str(_e)
    _db = None

_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
_STATUSES = {"open", "acknowledged", "resolved"}
_schema_ready = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require() -> None:
    if not NABLE_OK:
        raise HTTPException(status_code=503, detail=f"N-able connector unavailable: {_ERR}")
    _ensure_schema()


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    c = _db.conn
    c.execute(
        """CREATE TABLE IF NOT EXISTS network_alerts (
            id VARCHAR PRIMARY KEY,
            source VARCHAR DEFAULT 'nable',
            severity VARCHAR,
            alert_type VARCHAR,
            source_ip VARCHAR,
            dest_ip VARCHAR,
            dest_port INTEGER,
            bytes_transferred BIGINT,
            description VARCHAR,
            device_name VARCHAR,
            status VARCHAR DEFAULT 'open',
            notes VARCHAR,
            remediation VARCHAR,
            action_taken VARCHAR,
            acknowledged_by VARCHAR,
            acknowledged_at VARCHAR,
            resolved_by VARCHAR,
            resolved_at VARCHAR,
            created_at VARCHAR,
            updated_at VARCHAR
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS network_segments (
            id VARCHAR PRIMARY KEY,
            source VARCHAR DEFAULT 'nable',
            name VARCHAR,
            cidr VARCHAR,
            location VARCHAR,
            status VARCHAR DEFAULT 'active',
            created_at VARCHAR
        )"""
    )
    _schema_ready = True


def _audit(event: str, action: str, operator: str, details: Dict[str, Any]) -> None:
    """Best-effort write to the shared agent_logs trail."""
    try:
        _db.conn.execute(
            "INSERT INTO agent_logs (event, action, status, operator_id, details) "
            "VALUES (?, ?, 'success', ?, ?)",
            (event, action, operator, json.dumps(details)),
        )
    except Exception:  # noqa: BLE001
        logger.warning("nable audit write failed", exc_info=True)


def _uid(user: dict) -> str:
    return str(user.get("user_id") or user.get("id") or user.get("username") or "unknown")


class NableAlert(BaseModel):
    severity: str = Field(..., description="CRITICAL | HIGH | MEDIUM | LOW")
    alert_type: str = Field(..., description="dns_exfil, port_scan, data_burst, c2_callback, anomalous_traffic, ...")
    source_ip: str
    dest_ip: Optional[str] = None
    dest_port: Optional[int] = Field(None, ge=0, le=65535)
    bytes_transferred: Optional[int] = Field(None, ge=0)
    description: str = Field(..., max_length=2000)
    device_name: Optional[str] = None


class AlertAckRequest(BaseModel):
    notes: str = Field("", max_length=2000)


class AlertResolveRequest(BaseModel):
    remediation: str = Field(..., max_length=2000)
    action_taken: str = Field("", max_length=2000)


class SegmentRequest(BaseModel):
    name: str = Field(..., max_length=200)
    cidr: str = Field(..., max_length=64)
    location: str = Field("", max_length=200)


_ALERT_COLS = (
    "id, severity, alert_type, source_ip, dest_ip, dest_port, bytes_transferred, "
    "description, device_name, status, created_at, updated_at"
)


def _alert_row(r) -> Dict[str, Any]:
    return {
        "alert_id": r[0], "severity": r[1], "alert_type": r[2], "source_ip": r[3],
        "dest_ip": r[4], "dest_port": r[5], "bytes_transferred": r[6],
        "description": r[7], "device_name": r[8], "status": r[9],
        "created_at": r[10], "updated_at": r[11],
    }


@router.get("/alerts")
async def list_alerts(
    severity: Optional[str] = None,
    # NOT named "status": middleware/security_hardening.py whitelists any
    # parameter called "status" to the fleet values (online/offline/...).
    state: Optional[str] = Query(None, description="open, acknowledged, resolved"),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    _require()
    where, params = ["source = 'nable'"], []
    if severity:
        if severity.upper() not in _SEVERITIES:
            raise HTTPException(400, f"severity must be one of {sorted(_SEVERITIES)}")
        where.append("severity = ?"); params.append(severity.upper())
    if state:
        if state not in _STATUSES:
            raise HTTPException(400, f"state must be one of {sorted(_STATUSES)}")
        where.append("status = ?"); params.append(state)
    rows = _db.query(
        f"SELECT {_ALERT_COLS} FROM network_alerts WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC LIMIT ?",
        tuple(params + [limit]),
    )
    total = _db.query("SELECT COUNT(*) FROM network_alerts WHERE source = 'nable'")[0][0]
    open_n = _db.query(
        "SELECT COUNT(*) FROM network_alerts WHERE source = 'nable' AND status = 'open'"
    )[0][0]
    return {"ok": True, "alerts": [_alert_row(r) for r in rows],
            "total": total, "open": open_n, "timestamp": _now()}


def _transition(alert_id: str, sql: str, params: tuple) -> None:
    exists = _db.query("SELECT 1 FROM network_alerts WHERE id = ? AND source = 'nable'", (alert_id,))
    if not exists:
        raise HTTPException(404, f"Alert {alert_id} not found")
    _db.conn.execute(sql, params)


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: str, req: AlertAckRequest,
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    _require()
    now, uid = _now(), _uid(user)
    _transition(
        alert_id,
        "UPDATE network_alerts SET status='acknowledged', acknowledged_by=?, "
        "acknowledged_at=?, notes=?, updated_at=? WHERE id=?",
        (uid, now, req.notes, now, alert_id),
    )
    _audit("network_alert_acknowledged", "nable", uid, {"alert_id": alert_id})
    return {"ok": True, "alert_id": alert_id, "status": "acknowledged", "timestamp": now}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str, req: AlertResolveRequest,
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    _require()
    now, uid = _now(), _uid(user)
    _transition(
        alert_id,
        "UPDATE network_alerts SET status='resolved', resolved_by=?, resolved_at=?, "
        "remediation=?, action_taken=?, updated_at=? WHERE id=?",
        (uid, now, req.remediation, req.action_taken, now, alert_id),
    )
    _audit("network_alert_resolved", "nable", uid,
           {"alert_id": alert_id, "remediation": req.remediation})
    return {"ok": True, "alert_id": alert_id, "status": "resolved",
            "remediation": req.remediation, "timestamp": now}


@router.get("/networks")
async def list_networks(user: dict = Depends(get_authenticated_user)) -> Dict[str, Any]:
    _require()
    rows = _db.query(
        "SELECT id, name, cidr, location, status, created_at FROM network_segments "
        "WHERE source = 'nable' ORDER BY name"
    )
    nets: List[Dict[str, Any]] = []
    for r in rows:
        prefix = str(r[2]).split("/")[0].rsplit(".", 1)[0] + "."
        n = _db.query(
            "SELECT COUNT(*) FROM network_alerts WHERE source='nable' AND source_ip LIKE ?",
            (prefix + "%",),
        )[0][0]
        nets.append({"segment_id": r[0], "name": r[1], "cidr": r[2], "location": r[3],
                     "status": r[4], "alerts": n, "created_at": r[5]})
    return {"ok": True, "networks": nets, "total": len(nets), "timestamp": _now()}


@router.post("/networks")
async def add_network(req: SegmentRequest,
                      user: dict = Depends(get_authenticated_user)) -> Dict[str, Any]:
    _require()
    import ipaddress
    try:
        ipaddress.ip_network(req.cidr, strict=False)
    except ValueError:
        raise HTTPException(400, "cidr is not a valid network, e.g. 10.0.0.0/24")
    seg_id = f"seg-{uuid.uuid4().hex[:12]}"
    _db.conn.execute(
        "INSERT INTO network_segments (id, source, name, cidr, location, status, created_at) "
        "VALUES (?, 'nable', ?, ?, ?, 'active', ?)",
        (seg_id, req.name, req.cidr, req.location, _now()),
    )
    _audit("network_segment_added", "nable", _uid(user), {"segment_id": seg_id, "cidr": req.cidr})
    return {"ok": True, "segment_id": seg_id}


async def _webhook_auth(request: Request, x_nable_secret: Optional[str]) -> str:
    secret = os.environ.get("NABLE_WEBHOOK_SECRET", "")
    if secret:
        if x_nable_secret and hmac.compare_digest(x_nable_secret.encode(), secret.encode()):
            return "nable-webhook"
        raise HTTPException(401, "Invalid or missing X-Nable-Secret header")
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(
            401, "Webhook requires authentication. Set NABLE_WEBHOOK_SECRET and send it "
                 "as X-Nable-Secret, or authenticate as a user.")
    return _uid(user)


@router.post("/webhook")
async def receive_webhook(
    alert: NableAlert, request: Request,
    x_nable_secret: Optional[str] = Header(None),
) -> Dict[str, Any]:
    _require()
    caller = await _webhook_auth(request, x_nable_secret)
    sev = alert.severity.upper()
    if sev not in _SEVERITIES:
        raise HTTPException(400, f"severity must be one of {sorted(_SEVERITIES)}")
    alert_id, now = f"nable-{uuid.uuid4().hex[:16]}", _now()
    _db.conn.execute(
        "INSERT INTO network_alerts (id, source, severity, alert_type, source_ip, dest_ip, "
        "dest_port, bytes_transferred, description, device_name, status, created_at, updated_at) "
        "VALUES (?, 'nable', ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
        (alert_id, sev, alert.alert_type, alert.source_ip, alert.dest_ip, alert.dest_port,
         alert.bytes_transferred, alert.description, alert.device_name, now, now),
    )
    _audit("network_alert_ingested", "nable_webhook", caller,
           {"alert_id": alert_id, "alert_type": alert.alert_type, "severity": sev})
    return {"ok": True, "alert_id": alert_id, "status": "ingested", "timestamp": now}


@router.get("/status")
async def integration_status(user: dict = Depends(get_authenticated_user)) -> Dict[str, Any]:
    _require()
    last = _db.query("SELECT MAX(created_at) FROM network_alerts WHERE source='nable'")[0][0]
    open_n = _db.query(
        "SELECT COUNT(*) FROM network_alerts WHERE source='nable' AND status='open'")[0][0]
    segs = _db.query("SELECT COUNT(*) FROM network_segments WHERE source='nable'")[0][0]
    return {
        "ok": True,
        "connected": last is not None,
        "last_alert_received": last,
        "open_alerts": open_n,
        "monitored_networks": segs,
        "webhook_url": "/api/nable/webhook",
        "webhook_auth": "shared-secret" if os.environ.get("NABLE_WEBHOOK_SECRET") else "user-auth",
        "health": "degraded" if open_n >= 100 else "healthy",
        "timestamp": _now(),
    }
