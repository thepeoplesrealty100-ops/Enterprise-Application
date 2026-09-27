"""
backend/routers/vr_command_center.py — JAKAL Visual SOC Command Center
(v4.0, rebuilt).

A real 3D/visual threat map for the SOC, built from this platform's real
security telemetry — `findings` (severity/attack_technique), `network_map`
(discovered hosts + risk_score) and `global_fleet_matrix` (per-machine
predictive threat score / quarantine state) — plus real helmet/device
registration tied to real IAM identities (`users`/`user_roles`, the same
tables routers/iam.py manages) instead of a fabricated "clearance_level".

What this honestly has, and does not have:

  - It HAS a real device registry (helmet_id -> a real users.user_id),
    real ingested heartbeats, and a real 3D threat map whose *entities*
    (findings/hosts/machines) and *threat levels* are real DB rows. Each
    entity's (x, y, z) position is a DETERMINISTIC hash-based layout of
    its own id — a legitimate graph-visualization technique, not sensor
    telemetry, and documented as such rather than presented as GPS/LIDAR
    data this platform does not have.
  - It does NOT have VR hardware, a brain-computer interface, or
    drone/robotics control. Endpoints that would need one honestly return
    `not_configured` instead of the previous fabricated "attention_level",
    "neural_intent recognized" and "swarm_confirmation: acknowledged"
    content.
  - Any action against a real host (isolate, quarantine, YARA scan, kill
    process tree, fetch pcap, memory dump) is delegated to
    SecurityCapabilitiesEngine.execute() — same approval-gated path used
    by routers/av_command_center.py and routers/autonomous_response.py,
    never bypassed here.

This replaces the original v4.0 router's fictional "5000-unit defensive
swarm", brain-computer-interface telemetry, quantum-encrypted drone-swarm
control and per-domain "compliance_score" fixtures. Route paths, methods,
and the router variable name are unchanged — only content behind them is
real. Not used by any frontend page (confirmed: no "vr-command-center"
reference in index.html or js/).

Endpoints (all under /api/vr-command-center):
  POST /helmet/register                    — register a helmet to a real IAM user
  POST /helmet/heartbeat                   — ingest real device telemetry
  GET  /helmet/{helmet_id}/status          — last real heartbeat, or honest "no_heartbeat_received"
  POST /streams/vr-multiview               — configure a multiview against real av_command_center streams
  GET  /streams/vr/{helmet_id}/current-view — the real configured multiview
  POST /visualization/threat-space         — real 3D threat map (findings + hosts + machines)
  POST /visualization/threat-select        — real detail + allow-listed response options for one entity
  POST /neural/cognitive-assistance        — rule-based recommendation from real signals (edr:manage not required — read-only)
  POST /neural/decision-augmentation       — scores options against the real capabilities-engine registry
  POST /command/execute-encrypted          — allow-listed capabilities-engine action (edr:manage)
  POST /remote-control/drone-swarm         — not_configured (no drone hardware)
  POST /remote-control/autonomous-robot    — not_configured (no robotics hardware)
  WS   /ws/vr-helmet/{helmet_id}           — real control acks + situation snapshot, not a BCI echo
  GET  /command-center/situation           — real aggregate posture across findings/hosts/fleet
  POST /command-center/escalate-to-vr      — real, persisted escalation record
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from database import DuckDBManager, get_db_manager
from dependencies import get_authenticated_user, require_permission
from services.capabilities_engine import get_capabilities_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vr-command-center", tags=["Advanced VR Command Center"])

# Same allow-listed, host-response subset as routers/av_command_center.py —
# never a generic passthrough (that already exists at /api/capabilities/execute).
_ALLOWED_ACTIONS = {
    "fleet:isolate_host", "detect:quarantine_file", "detect:kill_process_tree",
    "detect:fetch_pcap", "detect:process_tree", "detect:memory_dump", "detect:scan_yara",
}

# Clearance is DERIVED from the operator's real IAM role (user_roles/roles),
# not a separate fabricated 0-5 scale. Unknown/no role -> 0.
_ROLE_CLEARANCE = {"root_admin": 5, "security_analyst": 3, "read_only": 1}


def _db() -> DuckDBManager:
    return get_db_manager()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_dict(db: DuckDBManager, row) -> Dict[str, Any]:
    cols = [d[0] for d in db.conn.description]
    return dict(zip(cols, row))


def _layout_xyz(entity_id: str, spread: float = 250.0) -> Dict[str, float]:
    """Deterministic pseudo-3D position for a real entity id — a graph-
    visualization layout technique (stable across calls, one point per
    real id), never sensor/GPS telemetry."""
    digest = hashlib.sha256(entity_id.encode("utf-8")).digest()
    x = (digest[0] / 255.0 - 0.5) * 2 * spread
    y = (digest[1] / 255.0 - 0.5) * 2 * spread
    z = (digest[2] / 255.0 - 0.5) * 2 * spread
    return {"x": round(x, 1), "y": round(y, 1), "z": round(z, 1)}


def _ensure_schema(db: DuckDBManager) -> None:
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS vr_helmet_registry (
            helmet_id TEXT PRIMARY KEY,
            operator_user_id TEXT NOT NULL,
            domain TEXT,
            status TEXT NOT NULL DEFAULT 'registered',
            battery_percentage INTEGER,
            signal_strength INTEGER,
            latency_ms INTEGER,
            active_streams INTEGER,
            performance_score DOUBLE,
            registered_at TIMESTAMPTZ DEFAULT now(),
            last_heartbeat_at TIMESTAMPTZ
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS vr_multiview_configs (
            helmet_id TEXT PRIMARY KEY,
            config_id TEXT NOT NULL,
            stream_ids TEXT NOT NULL,
            layout_mode TEXT NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS vr_escalations (
            escalation_id TEXT PRIMARY KEY,
            helmet_id TEXT,
            situation TEXT,
            priority TEXT NOT NULL DEFAULT 'normal',
            acknowledged BOOLEAN DEFAULT false,
            created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db.conn.commit()


def _audit(db: DuckDBManager, request: Request, user: dict, action: str, outcome: str,
           resource_id: str = "", detail: Optional[Dict[str, Any]] = None) -> None:
    try:
        db.insert_audit_entry({
            "actor_user_id": user["user_id"], "actor_label": user["username"],
            "action": action, "resource_type": "vr_command_center", "resource_id": resource_id,
            "outcome": outcome, "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("audit write failed for %s", action)


def _clearance_for(db: DuckDBManager, user_id: str) -> Dict[str, Any]:
    row = db.conn.execute(
        "SELECT role_key FROM user_roles WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone()
    role_key = row[0] if row else None
    return {"role_key": role_key, "clearance_level": _ROLE_CLEARANCE.get(role_key, 0)}


# ══════════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════════

class VRHeartbeat(BaseModel):
    helmet_id: str = Field(..., max_length=100)
    battery_percentage: int = Field(..., ge=0, le=100)
    signal_strength: int = Field(..., ge=0, le=100)
    latency_ms: int = Field(..., ge=0)
    active_streams: int = Field(default=0, ge=0)
    performance_score: float = Field(default=0.0, ge=0.0, le=100.0)


class CommandDecision(BaseModel):
    decision_id: str = Field(..., max_length=100)
    threat_id: str = Field(..., max_length=200)
    decision_type: str = Field(..., max_length=100)
    authorized_by: str = Field(..., max_length=200)
    action_id: Optional[str] = Field(default=None, max_length=100)
    response_payload: Dict[str, Any] = Field(default_factory=dict)


class EscalationRequest(BaseModel):
    situation: Dict[str, Any] = Field(default_factory=dict)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")


# ══════════════════════════════════════════════════════════════════════════
# Helmet registration / telemetry
# ══════════════════════════════════════════════════════════════════════════

@router.post("/helmet/register")
async def register_helmet(operator_id: str, helmet_serial: str, domain: str,
                           request: Request, db: DuckDBManager = Depends(_db),
                           user: dict = Depends(get_authenticated_user)):
    _ensure_schema(db)
    real_user = db.conn.execute(
        "SELECT user_id FROM users WHERE user_id = ?", (operator_id,)
    ).fetchone()
    if not real_user:
        raise HTTPException(status_code=404, detail=f"operator_id '{operator_id}' is not a real IAM user")
    helmet_id = f"vr-{helmet_serial}"
    db.conn.execute(
        """INSERT INTO vr_helmet_registry (helmet_id, operator_user_id, domain, status)
           VALUES (?, ?, ?, 'registered')
           ON CONFLICT (helmet_id) DO UPDATE SET operator_user_id = excluded.operator_user_id,
               domain = excluded.domain, status = 'registered'""",
        (helmet_id, operator_id, domain),
    )
    db.conn.commit()
    clearance = _clearance_for(db, operator_id)
    _audit(db, request, user, "register_helmet", "success", helmet_id, {"operator_id": operator_id, "domain": domain})
    return {"helmet_id": helmet_id, "operator_id": operator_id, "domain": domain,
            "registration_status": "registered", **clearance, "timestamp": _now_iso()}


@router.post("/helmet/heartbeat")
async def helmet_heartbeat(heartbeat: VRHeartbeat, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    existing = db.conn.execute(
        "SELECT helmet_id FROM vr_helmet_registry WHERE helmet_id = ?", (heartbeat.helmet_id,)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"helmet {heartbeat.helmet_id} is not registered")
    status = "healthy" if heartbeat.battery_percentage > 20 else "low_battery"
    db.conn.execute(
        """UPDATE vr_helmet_registry SET status = ?, battery_percentage = ?, signal_strength = ?,
           latency_ms = ?, active_streams = ?, performance_score = ?, last_heartbeat_at = now()
           WHERE helmet_id = ?""",
        (status, heartbeat.battery_percentage, heartbeat.signal_strength, heartbeat.latency_ms,
         heartbeat.active_streams, heartbeat.performance_score, heartbeat.helmet_id),
    )
    db.conn.commit()
    return {"helmet_id": heartbeat.helmet_id, "status": status, "acknowledgment": "received", "timestamp": _now_iso()}


@router.get("/helmet/{helmet_id}/status")
async def helmet_status(helmet_id: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    row = db.conn.execute("SELECT * FROM vr_helmet_registry WHERE helmet_id = ?", (helmet_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"helmet {helmet_id} is not registered")
    data = _row_dict(db, row)
    if not data.get("last_heartbeat_at"):
        data["status"] = "no_heartbeat_received"
    return {**data, "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# Multiview — configured against real av_command_center streams
# ══════════════════════════════════════════════════════════════════════════

@router.post("/streams/vr-multiview")
async def multiview_streams(helmet_id: str, stream_ids: List[str], db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    if not stream_ids:
        raise HTTPException(status_code=422, detail="stream_ids must not be empty")
    rows = db.conn.execute(
        "SELECT stream_id FROM av_stream_registry WHERE stream_id IN "
        + "(" + ", ".join(["?"] * len(stream_ids)) + ")",
        stream_ids,
    ).fetchall()
    found = {r[0] for r in rows}
    missing = [s for s in stream_ids if s not in found]
    config_id = str(uuid.uuid4())
    db.conn.execute(
        """INSERT INTO vr_multiview_configs (helmet_id, config_id, stream_ids, layout_mode)
           VALUES (?, ?, ?, 'quad_view')
           ON CONFLICT (helmet_id) DO UPDATE SET config_id = excluded.config_id,
               stream_ids = excluded.stream_ids, updated_at = now()""",
        (helmet_id, config_id, json.dumps(stream_ids)),
    )
    db.conn.commit()
    return {"helmet_id": helmet_id, "multiview_id": config_id, "streams_configured": len(found),
            "missing_streams": missing, "layout_mode": "quad_view", "timestamp": _now_iso()}


@router.get("/streams/vr/{helmet_id}/current-view")
async def current_vr_view(helmet_id: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    cfg = db.conn.execute(
        "SELECT * FROM vr_multiview_configs WHERE helmet_id = ?", (helmet_id,)
    ).fetchone()
    if not cfg:
        return {"helmet_id": helmet_id, "current_view": None,
                "reason": "no multiview configured for this helmet", "timestamp": _now_iso()}
    cfg = _row_dict(db, cfg)
    stream_ids = json.loads(cfg["stream_ids"])
    views = []
    for sid in stream_ids:
        row = db.conn.execute("SELECT * FROM av_stream_registry WHERE stream_id = ?", (sid,)).fetchone()
        views.append(_row_dict(db, row) if row else {"stream_id": sid, "status": "missing"})
    return {"helmet_id": helmet_id, "multiview_id": cfg["config_id"], "layout_mode": cfg["layout_mode"],
            "views": views, "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# 3D threat map — real findings + hosts + machines, deterministic layout
# ══════════════════════════════════════════════════════════════════════════

@router.post("/visualization/threat-space")
async def threat_3d_space(helmet_id: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    threat_objects: List[Dict[str, Any]] = []

    for fid, severity, title, technique in db.conn.execute(
        "SELECT id, severity, title, attack_technique FROM findings ORDER BY created_at DESC LIMIT 25"
    ).fetchall():
        entity_id = f"finding-{fid}"
        level = {"critical": 95, "high": 75, "medium": 50, "low": 25}.get((severity or "").lower(), 10)
        threat_objects.append({
            "threat_id": entity_id, "type": "finding", "location_3d": _layout_xyz(entity_id),
            "threat_level": level, "label": title or f"Finding #{fid}", "attack_technique": technique,
        })

    for ip, hostname, risk_score in db.conn.execute(
        "SELECT ip_address, hostname, risk_score FROM network_map WHERE risk_score > 0 ORDER BY risk_score DESC LIMIT 25"
    ).fetchall():
        entity_id = f"host-{ip}"
        threat_objects.append({
            "threat_id": entity_id, "type": "network_host", "location_3d": _layout_xyz(entity_id),
            "threat_level": min(100, round(float(risk_score) * 10)), "label": hostname or ip,
        })

    for machine_id, score, quarantined in db.conn.execute(
        "SELECT machine_id, predictive_threat_score, is_quarantined FROM global_fleet_matrix"
    ).fetchall():
        entity_id = f"machine-{machine_id}"
        level = 100 if quarantined else min(100, round((score or 0) * 100))
        threat_objects.append({
            "threat_id": entity_id, "type": "fleet_machine", "location_3d": _layout_xyz(entity_id),
            "threat_level": level, "label": machine_id, "is_quarantined": bool(quarantined),
        })

    threat_objects.sort(key=lambda t: t["threat_level"], reverse=True)
    return {
        "visualization_id": str(uuid.uuid4()), "helmet_id": helmet_id,
        "space": {"center_coordinates": {"x": 0, "y": 0, "z": 0}, "viewport_range_meters": 250,
                  "layout_note": "location_3d is a deterministic hash-based layout of the entity's real id, not sensor telemetry",
                  "threat_objects": threat_objects},
        "timestamp": _now_iso(),
    }


@router.post("/visualization/threat-select")
async def threat_select(helmet_id: str, threat_id: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    kind, _, ref = threat_id.partition("-")
    detail: Optional[Dict[str, Any]] = None
    if kind == "finding":
        row = db.conn.execute("SELECT * FROM findings WHERE id = ?", (ref,)).fetchone()
        detail = _row_dict(db, row) if row else None
    elif kind == "host":
        row = db.conn.execute("SELECT * FROM network_map WHERE ip_address = ?", (ref,)).fetchone()
        detail = _row_dict(db, row) if row else None
    elif kind == "machine":
        row = db.conn.execute("SELECT * FROM global_fleet_matrix WHERE machine_id = ?", (ref,)).fetchone()
        detail = _row_dict(db, row) if row else None
    if detail is None:
        raise HTTPException(status_code=404, detail=f"threat_id '{threat_id}' not found")

    engine = get_capabilities_engine(db)
    recommended_actions = []
    for action_id in sorted(_ALLOWED_ACTIONS):
        meta = engine.actions.get(action_id)
        if meta:
            recommended_actions.append({
                "action_id": action_id, "category": getattr(meta, "category", None),
                "risk_level": getattr(meta, "risk_level", None),
                "authorization_required": str(getattr(meta, "risk_level", "")).lower() in ("high", "critical"),
            })
    return {"helmet_id": helmet_id, "threat_id": threat_id, "selected": True,
            "entity_type": kind, "detail": detail, "recommended_actions": recommended_actions,
            "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# Decision support — honest about the absent BCI; real signal-driven and
# real capabilities-registry-driven recommendations
# ══════════════════════════════════════════════════════════════════════════

@router.post("/neural/cognitive-assistance")
async def cognitive_assistance(helmet_id: str, context: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    critical_findings = db.conn.execute(
        "SELECT COUNT(*) FROM findings WHERE severity = 'critical'"
    ).fetchone()[0]
    quarantined = db.conn.execute(
        "SELECT COUNT(*) FROM global_fleet_matrix WHERE is_quarantined = true"
    ).fetchone()[0]
    if quarantined:
        recommendation = f"{quarantined} machine(s) already quarantined — review containment status."
    elif critical_findings:
        recommendation = f"{critical_findings} open critical finding(s) — prioritize triage."
    else:
        recommendation = "No critical findings or quarantined machines currently on record."
    return {
        "helmet_id": helmet_id, "context": context,
        "cognitive_recommendations": [{"recommendation": recommendation,
                                        "critical_findings": critical_findings, "quarantined_machines": quarantined}],
        "brain_computer_interface": {"status": "not_configured",
                                      "reason": "No BCI hardware is wired to this platform."},
        "timestamp": _now_iso(),
    }


@router.post("/neural/decision-augmentation")
async def decision_augmentation(helmet_id: str, decision_options: List[str], db: DuckDBManager = Depends(_db)):
    engine = get_capabilities_engine(db)
    analysis = {}
    for i, choice in enumerate(decision_options):
        meta = engine.actions.get(choice)
        if meta:
            analysis[f"option_{i + 1}"] = {"choice": choice, "known_action": True,
                                            "category": getattr(meta, "category", None),
                                            "risk_level": getattr(meta, "risk_level", None)}
        else:
            analysis[f"option_{i + 1}"] = {"choice": choice, "known_action": False,
                                            "reason": "not a recognized capabilities-engine action_id"}
    recommended = next((o["choice"] for o in analysis.values() if o.get("known_action")), None)
    return {"helmet_id": helmet_id, "analysis": analysis, "recommended_choice": recommended,
            "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# Command execution — real, approval-gated capabilities-engine delegation
# ══════════════════════════════════════════════════════════════════════════

@router.post("/command/execute-encrypted", dependencies=[require_permission("edr:manage")])
async def execute_encrypted_command(helmet_id: str, decision: CommandDecision, request: Request,
                                     db: DuckDBManager = Depends(_db), user: dict = Depends(get_authenticated_user)):
    action_id = decision.action_id
    if not action_id or action_id not in _ALLOWED_ACTIONS:
        raise HTTPException(status_code=422, detail=f"decision.action_id must be one of {sorted(_ALLOWED_ACTIONS)}")
    engine = get_capabilities_engine(db)
    payload = dict(decision.response_payload)
    result = await engine.execute(action_id, payload, executor=decision.authorized_by, approved=False)
    _audit(db, request, user, "execute_encrypted_command", "requested", helmet_id,
           {"decision_id": decision.decision_id, "action_id": action_id, "engine_result": result})
    return {"command_id": str(uuid.uuid4()), "helmet_id": helmet_id, "decision_id": decision.decision_id,
            "action_id": action_id, "engine_result": result, "timestamp": _now_iso()}


@router.post("/remote-control/drone-swarm")
async def drone_swarm_control(helmet_id: str, command: Dict[str, Any]):
    return {"helmet_id": helmet_id, "status": "not_configured",
            "reason": "No drone-swarm hardware or control link is wired to this platform.", "timestamp": _now_iso()}


@router.post("/remote-control/autonomous-robot")
async def robot_control(helmet_id: str, robot_id: str, command: Dict[str, Any]):
    return {"helmet_id": helmet_id, "robot_id": robot_id, "status": "not_configured",
            "reason": "No robotics hardware or control link is wired to this platform.", "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# WebSocket — real acks + a real situation snapshot, not a BCI echo
# ══════════════════════════════════════════════════════════════════════════

@router.websocket("/ws/vr-helmet/{helmet_id}")
async def websocket_vr_helmet(websocket: WebSocket, helmet_id: str):
    await websocket.accept()
    db = get_db_manager()
    _ensure_schema(db)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                control_data = json.loads(data)
            except Exception:
                control_data = {}
            control_type = control_data.get("type", "unknown")
            processed = control_type in ("head_tracking", "gesture", "voice_command")
            critical_findings = db.conn.execute(
                "SELECT COUNT(*) FROM findings WHERE severity = 'critical'"
            ).fetchone()[0]
            await websocket.send_json({
                "type": "command_acknowledgment",
                "response": {"processed": processed, "control_type": control_type},
                "situation": {"critical_findings": critical_findings},
                "timestamp": _now_iso(),
            })
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("vr-helmet websocket error for %s", helmet_id)


# ══════════════════════════════════════════════════════════════════════════
# Command center — real aggregate posture
# ══════════════════════════════════════════════════════════════════════════

@router.get("/command-center/situation")
async def situation_awareness(db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    finding_counts = dict(db.conn.execute(
        "SELECT severity, COUNT(*) FROM findings GROUP BY severity"
    ).fetchall())
    host_count, avg_risk = db.conn.execute(
        "SELECT COUNT(*), COALESCE(AVG(risk_score), 0) FROM network_map"
    ).fetchone()
    fleet_total, quarantined = db.conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN is_quarantined THEN 1 ELSE 0 END) FROM global_fleet_matrix"
    ).fetchone()
    engine = get_capabilities_engine(db)
    pending = len(engine.pending_approvals())
    return {
        "timestamp": _now_iso(),
        "findings_by_severity": finding_counts,
        "network_hosts_tracked": host_count, "average_host_risk_score": round(float(avg_risk or 0), 2),
        "fleet_machines_tracked": fleet_total or 0, "fleet_machines_quarantined": quarantined or 0,
        "pending_capability_approvals": pending,
    }


@router.post("/command-center/escalate-to-vr")
async def escalate_to_vr(helmet_id: str, req: EscalationRequest, request: Request,
                          db: DuckDBManager = Depends(_db), user: dict = Depends(get_authenticated_user)):
    _ensure_schema(db)
    escalation_id = str(uuid.uuid4())
    db.conn.execute(
        """INSERT INTO vr_escalations (escalation_id, helmet_id, situation, priority, created_by)
           VALUES (?, ?, ?, ?, ?)""",
        (escalation_id, helmet_id, json.dumps(req.situation, default=str), req.priority, user["username"]),
    )
    db.conn.commit()
    _audit(db, request, user, "escalate_to_vr", "success", helmet_id, {"escalation_id": escalation_id})
    return {"escalation_id": escalation_id, "helmet_id": helmet_id, "priority": req.priority,
            "timestamp": _now_iso()}
