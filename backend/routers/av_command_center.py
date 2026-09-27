"""
backend/routers/av_command_center.py — JAKAL A/V + Sensor/EDR Fusion Center
(v4.0, rebuilt).

Real camera/audio stream *registry* + real sensor-threshold ingestion,
fused against the two real security-telemetry sources this platform
actually has — `global_fleet_matrix` (per-machine predictive threat score
/ quarantine state) and the Security Capabilities Engine
(services/capabilities_engine.py, the same 34-action registry backing
routers/capabilities.py, routers/soar.py and routers/autonomous_response.py).

What this honestly has, and does not have:

  - It HAS a real, DB-backed registry of camera/audio sources an operator
    can register (name, type, RTSP URL, resolution, zone) and a real
    ingestion path for sensor readings, which are persisted and evaluated
    against their own threshold in `av_sensor_readings`.
  - It does NOT decode video, run object-detection ML, or transcribe
    audio — no such pipeline exists in this environment. Endpoints that
    would need one honestly return `not_configured` instead of the
    previous behavior of returning fabricated bounding boxes, transcripts
    and "gunshot"/"drone" classifications with no underlying data.
  - "Sensory fusion" here means: registered stream/sensor state, joined
    by `zone` against `global_fleet_matrix.network_segment`, surfaced as
    real correlation events — not a fabricated "neural cortex".
  - A `POST /streams/connect` with a real `rtsp_url` gets an honest TCP
    reachability probe (connect-or-timeout to host:port) instead of an
    unconditional "connected": true.
  - Any action against a real host (isolate, quarantine, kill process
    tree, fetch pcap, memory dump, YARA scan) is delegated to
    SecurityCapabilitiesEngine.execute() — same approval-gated path as
    everywhere else, never bypassed here.

This replaces the original v4.0 router's fictional 4K/thermal/multispectral
mock stream list, fake YOLO/anomaly-detector object detection, invented
gunshot/explosion audio classification and "nanoswarm deployment"
response-decision content. Route paths, methods and the router variable
name are unchanged — only content behind them is real. Not used by any
frontend page (confirmed: no "av-command" reference in index.html or js/).

Endpoints (all under /api/av-command):
  GET  /streams/active                    — real registry + bandwidth total
  POST /streams/connect                   — register + TCP-probe a stream (edr:manage)
  POST /streams/{stream_id}/record        — stage a recording request (edr:manage; honest
                                             pending_capture_agent — no capture agent exists)
  GET  /streams/{stream_id}/metadata       — real registry row
  POST /ai-detection/enable                — enable EDR/fleet correlation for a stream (edr:manage)
  GET  /ai-detection/results               — real correlation events for a stream
  POST /ai-detection/alert                 — escalate a correlation event (edr:manage)
  POST /audio/transcribe                   — not_configured (no STT engine)
  GET  /audio/analysis                     — real acoustic-sensor threshold analysis for a stream's zone
  POST /audio/threat-classify              — not_configured (no audio-ML classifier)
  GET  /sensors/status                     — real latest-reading-per-sensor, grouped by zone
  POST /sensors/trigger-check              — ingest real readings, evaluate against threshold
  GET  /sensors/correlation                — fuse sensor breaches with global_fleet_matrix by zone
  POST /neural/sensory-fusion              — composite real snapshot for one stream
  POST /neural/threat-reasoning            — real rule-based recommendation from real signals
  POST /neural/response-decision           — stage the recommended action via capabilities engine (edr:manage)
  POST /command/execute                    — direct, allow-listed capabilities-engine action (edr:manage)
  WS   /ws/av-stream/{stream_id}           — pushes real correlation events, not an echo ack
"""
from __future__ import annotations

import json
import logging
import socket
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from database import DuckDBManager, get_db_manager
from dependencies import get_authenticated_user, require_permission
from services.capabilities_engine import get_capabilities_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/av-command", tags=["A/V Command Center"])

# Threshold above which a real global_fleet_matrix.predictive_threat_score
# counts as "elevated" for correlation/reasoning purposes. Documented here
# rather than fabricated per-call, since the column's own comment implies
# a 0.0-1.0 range but the codebase has no existing fixed cutoff for it.
_THREAT_SCORE_ALERT = 0.7

# Allow-listed capabilities-engine actions this router may invoke directly
# (POST /command/execute, POST /neural/response-decision) — a small,
# EDR/host-response subset of the full 34-action registry, not a generic
# passthrough (that already exists at /api/capabilities/execute).
_ALLOWED_ACTIONS = {
    "fleet:isolate_host", "detect:quarantine_file", "detect:kill_process_tree",
    "detect:fetch_pcap", "detect:process_tree", "detect:memory_dump", "detect:scan_yara",
}


def _db() -> DuckDBManager:
    return get_db_manager()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(db: DuckDBManager) -> None:
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS av_stream_registry (
            stream_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            stream_type TEXT NOT NULL,
            rtsp_url TEXT,
            resolution TEXT,
            bitrate_kbps INTEGER DEFAULT 0,
            zone TEXT,
            status TEXT NOT NULL,
            correlation_enabled BOOLEAN DEFAULT false,
            created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS av_sensor_readings (
            reading_id TEXT PRIMARY KEY,
            sensor_id TEXT NOT NULL,
            sensor_type TEXT,
            zone TEXT,
            reading_value DOUBLE NOT NULL,
            reading_unit TEXT,
            threshold DOUBLE,
            recorded_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS av_correlation_events (
            event_id TEXT PRIMARY KEY,
            stream_id TEXT,
            zone TEXT,
            event_type TEXT NOT NULL,
            threat_level TEXT NOT NULL,
            source TEXT NOT NULL,
            correlated_machine_id TEXT,
            detail TEXT,
            escalated BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS av_recording_requests (
            request_id TEXT PRIMARY KEY,
            stream_id TEXT NOT NULL,
            requested_duration_seconds INTEGER,
            status TEXT NOT NULL,
            reason TEXT,
            requested_by TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db.conn.commit()


def _audit(db: DuckDBManager, request: Request, user: dict, action: str, outcome: str,
           resource_id: str = "", detail: Optional[Dict[str, Any]] = None) -> None:
    try:
        db.insert_audit_entry({
            "actor_user_id": user["user_id"], "actor_label": user["username"],
            "action": action, "resource_type": "av_command_center", "resource_id": resource_id,
            "outcome": outcome, "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("audit write failed for %s", action)


def _probe_tcp(rtsp_url: str, timeout_seconds: float = 2.0) -> bool:
    """Honest reachability probe: real TCP connect-or-timeout to the
    stream source's host:port. Never claims "connected" without this."""
    try:
        parsed = urlparse(rtsp_url)
        host = parsed.hostname
        port = parsed.port or (554 if parsed.scheme in ("rtsp", "rtsps") else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except Exception:
        return False


def _row_dict(db: DuckDBManager, row) -> Dict[str, Any]:
    cols = [d[0] for d in db.conn.description]
    return dict(zip(cols, row))


# ══════════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════════

class StreamConfig(BaseModel):
    stream_name: str = Field(..., max_length=200)
    stream_type: str = Field(..., max_length=50)
    rtsp_url: Optional[str] = Field(default=None, max_length=500)
    resolution: str = Field(default="1080p", max_length=20)
    bitrate_kbps: int = Field(default=2500, ge=0)
    zone: Optional[str] = Field(default=None, max_length=100)


class SensorReading(BaseModel):
    sensor_id: str = Field(..., max_length=100)
    sensor_type: Optional[str] = Field(default=None, max_length=50)
    zone: Optional[str] = Field(default=None, max_length=100)
    reading_value: float
    reading_unit: str = Field(default="", max_length=20)
    threshold: Optional[float] = None


class TriggerCheckRequest(BaseModel):
    readings: List[SensorReading] = Field(default_factory=list)


class CommandExecuteRequest(BaseModel):
    action_id: str = Field(..., max_length=100)
    payload: Dict[str, Any] = Field(default_factory=dict)
    stream_id: Optional[str] = None
    operator_id: str = Field(default="system")


class ThreatReasoningRequest(BaseModel):
    zone: str = Field(..., max_length=100)
    stream_id: Optional[str] = None


class ResponseDecisionRequest(BaseModel):
    action_id: str = Field(..., max_length=100)
    target_machine_id: str = Field(..., max_length=200)
    zone: Optional[str] = Field(default=None, max_length=100)
    operator_id: str = Field(default="system")


# ══════════════════════════════════════════════════════════════════════════
# Stream registry
# ══════════════════════════════════════════════════════════════════════════

@router.get("/streams/active")
async def get_active_streams(db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    rows = db.conn.execute(
        "SELECT * FROM av_stream_registry ORDER BY created_at DESC"
    ).fetchall()
    streams = [_row_dict(db, r) for r in rows]
    total_bandwidth_mbps = round(sum((s.get("bitrate_kbps") or 0) for s in streams) / 1000.0, 2)
    return {"active_streams": len(streams), "streams": streams,
            "total_bandwidth_mbps": total_bandwidth_mbps, "timestamp": _now_iso()}


@router.post("/streams/connect", dependencies=[require_permission("edr:manage")])
async def connect_stream(config: StreamConfig, request: Request, db: DuckDBManager = Depends(_db),
                          user: dict = Depends(get_authenticated_user)):
    stream_id = str(uuid.uuid4())
    if config.rtsp_url:
        reachable = _probe_tcp(config.rtsp_url)
        status = "connected" if reachable else "unreachable"
    else:
        status = "registered_no_source"
    db.conn.execute(
        """INSERT INTO av_stream_registry
           (stream_id, name, stream_type, rtsp_url, resolution, bitrate_kbps, zone, status, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (stream_id, config.stream_name, config.stream_type, config.rtsp_url,
         config.resolution, config.bitrate_kbps, config.zone, status, user["username"]),
    )
    db.conn.commit()
    _audit(db, request, user, "connect_stream", status, stream_id, {"stream_type": config.stream_type})
    return {"stream_id": stream_id, "name": config.stream_name, "status": status,
            "connection_time": _now_iso(), "bitrate_kbps": config.bitrate_kbps, "timestamp": _now_iso()}


@router.post("/streams/{stream_id}/record", dependencies=[require_permission("edr:manage")])
async def record_stream(stream_id: str, request: Request, duration_seconds: int = 3600,
                         db: DuckDBManager = Depends(_db), user: dict = Depends(get_authenticated_user)):
    _ensure_schema(db)
    stream = db.conn.execute(
        "SELECT stream_id FROM av_stream_registry WHERE stream_id = ?", (stream_id,)
    ).fetchone()
    if not stream:
        raise HTTPException(status_code=404, detail=f"stream {stream_id} not found")
    request_id = str(uuid.uuid4())
    reason = ("No video-capture agent is wired to this stream in this deployment — this platform "
              "does not have a media pipeline able to actually record. The request is recorded so an "
              "operator or a future capture-agent integration can act on it.")
    db.conn.execute(
        """INSERT INTO av_recording_requests
           (request_id, stream_id, requested_duration_seconds, status, reason, requested_by)
           VALUES (?, ?, ?, 'pending_capture_agent', ?, ?)""",
        (request_id, stream_id, duration_seconds, reason, user["username"]),
    )
    db.conn.commit()
    _audit(db, request, user, "request_recording", "pending_capture_agent", stream_id, {"request_id": request_id})
    return {"request_id": request_id, "stream_id": stream_id, "status": "pending_capture_agent",
            "reason": reason, "timestamp": _now_iso()}


@router.get("/streams/{stream_id}/metadata")
async def stream_metadata(stream_id: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    row = db.conn.execute(
        "SELECT * FROM av_stream_registry WHERE stream_id = ?", (stream_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"stream {stream_id} not found")
    return {**_row_dict(db, row), "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# EDR/fleet correlation ("AI detection" — now real, not fabricated video ML)
# ══════════════════════════════════════════════════════════════════════════

@router.post("/ai-detection/enable", dependencies=[require_permission("edr:manage")])
async def enable_ai_detection(stream_id: str, request: Request, db: DuckDBManager = Depends(_db),
                               user: dict = Depends(get_authenticated_user)):
    _ensure_schema(db)
    row = db.conn.execute(
        "SELECT zone FROM av_stream_registry WHERE stream_id = ?", (stream_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"stream {stream_id} not found")
    db.conn.execute(
        "UPDATE av_stream_registry SET correlation_enabled = true, updated_at = now() WHERE stream_id = ?",
        (stream_id,),
    )
    db.conn.commit()
    _audit(db, request, user, "enable_correlation", "success", stream_id)
    return {"stream_id": stream_id, "correlation_enabled": True, "zone": row[0], "timestamp": _now_iso()}


@router.get("/ai-detection/results")
async def detection_results(stream_id: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    rows = db.conn.execute(
        "SELECT * FROM av_correlation_events WHERE stream_id = ? ORDER BY created_at DESC LIMIT 100",
        (stream_id,),
    ).fetchall()
    events = [_row_dict(db, r) for r in rows]
    return {"stream_id": stream_id, "detection_timestamp": _now_iso(),
            "correlation_events": events, "count": len(events)}


@router.post("/ai-detection/alert", dependencies=[require_permission("edr:manage")])
async def ai_detection_alert(event_id: str, request: Request, db: DuckDBManager = Depends(_db),
                              user: dict = Depends(get_authenticated_user)):
    _ensure_schema(db)
    row = db.conn.execute(
        "SELECT * FROM av_correlation_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"correlation event {event_id} not found")
    db.conn.execute(
        "UPDATE av_correlation_events SET escalated = true WHERE event_id = ?", (event_id,)
    )
    db.conn.commit()
    event = _row_dict(db, row)
    _audit(db, request, user, "escalate_correlation_event", "success", event_id, event)
    return {"event_id": event_id, "escalated": True, "event": event, "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# Audio — honest about the missing STT/classifier pipeline; real for
# sensor-backed acoustic analysis
# ══════════════════════════════════════════════════════════════════════════

@router.post("/audio/transcribe")
async def transcribe_audio(stream_id: str):
    return {"stream_id": stream_id, "status": "not_configured",
            "reason": "No speech-to-text engine is wired to this platform.", "timestamp": _now_iso()}


@router.get("/audio/analysis")
async def audio_analysis(stream_id: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    stream = db.conn.execute(
        "SELECT zone FROM av_stream_registry WHERE stream_id = ?", (stream_id,)
    ).fetchone()
    if not stream:
        raise HTTPException(status_code=404, detail=f"stream {stream_id} not found")
    zone = stream[0]
    rows = db.conn.execute(
        """SELECT * FROM av_sensor_readings
           WHERE zone = ? AND sensor_type ILIKE 'acoustic%'
           ORDER BY recorded_at DESC LIMIT 50""",
        (zone,),
    ).fetchall()
    readings = [_row_dict(db, r) for r in rows]
    breaches = [r for r in readings if r.get("threshold") is not None and r["reading_value"] > r["threshold"]]
    return {"stream_id": stream_id, "zone": zone, "analysis_timestamp": _now_iso(),
            "acoustic_readings": readings, "threshold_breaches": breaches}


@router.post("/audio/threat-classify")
async def classify_audio_threat(stream_id: str, audio_data: Optional[Dict[str, Any]] = None):
    return {"stream_id": stream_id, "status": "not_configured",
            "reason": "No audio-ML threat classifier is wired to this platform.", "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# Sensors — real ingestion + threshold evaluation + fleet correlation
# ══════════════════════════════════════════════════════════════════════════

@router.get("/sensors/status")
async def sensor_status(db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    rows = db.conn.execute("""
        SELECT r.* FROM av_sensor_readings r
        INNER JOIN (
            SELECT sensor_id, MAX(recorded_at) AS latest FROM av_sensor_readings GROUP BY sensor_id
        ) m ON r.sensor_id = m.sensor_id AND r.recorded_at = m.latest
        ORDER BY r.zone, r.sensor_id
    """).fetchall()
    latest = [_row_dict(db, r) for r in rows]
    by_zone: Dict[str, List[Dict[str, Any]]] = {}
    for reading in latest:
        by_zone.setdefault(reading.get("zone") or "unassigned", []).append(reading)
    online = sum(1 for r in latest if r.get("reading_value") is not None)
    return {"total_sensors": len(latest), "sensors_reporting": online,
            "zones": by_zone, "timestamp": _now_iso()}


@router.post("/sensors/trigger-check")
async def check_sensor_triggers(req: TriggerCheckRequest, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    for reading in req.readings:
        db.conn.execute(
            """INSERT INTO av_sensor_readings
               (reading_id, sensor_id, sensor_type, zone, reading_value, reading_unit, threshold)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), reading.sensor_id, reading.sensor_type, reading.zone,
             reading.reading_value, reading.reading_unit, reading.threshold),
        )
    if req.readings:
        db.conn.commit()

    rows = db.conn.execute("""
        SELECT r.* FROM av_sensor_readings r
        INNER JOIN (
            SELECT sensor_id, MAX(recorded_at) AS latest FROM av_sensor_readings GROUP BY sensor_id
        ) m ON r.sensor_id = m.sensor_id AND r.recorded_at = m.latest
        WHERE r.threshold IS NOT NULL AND r.reading_value > r.threshold
    """).fetchall()
    triggered = [_row_dict(db, r) for r in rows]
    return {"check_timestamp": _now_iso(), "triggers_exceeded": len(triggered), "triggered_sensors": triggered}


@router.get("/sensors/correlation")
async def correlate_sensors(db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    triggered_rows = db.conn.execute("""
        SELECT r.* FROM av_sensor_readings r
        INNER JOIN (
            SELECT sensor_id, MAX(recorded_at) AS latest FROM av_sensor_readings GROUP BY sensor_id
        ) m ON r.sensor_id = m.sensor_id AND r.recorded_at = m.latest
        WHERE r.threshold IS NOT NULL AND r.reading_value > r.threshold AND r.zone IS NOT NULL
    """).fetchall()
    triggered = [_row_dict(db, r) for r in triggered_rows]

    correlated_events: List[Dict[str, Any]] = []
    for breach in triggered:
        zone = breach["zone"]
        fleet_rows = db.conn.execute(
            """SELECT machine_id, predictive_threat_score, is_quarantined FROM global_fleet_matrix
               WHERE network_segment = ? AND (predictive_threat_score >= ? OR is_quarantined = true)""",
            (zone, _THREAT_SCORE_ALERT),
        ).fetchall()
        for machine_id, score, quarantined in fleet_rows:
            event_id = str(uuid.uuid4())
            threat_level = "critical" if quarantined else ("high" if (score or 0) >= _THREAT_SCORE_ALERT else "medium")
            detail = {"sensor_id": breach["sensor_id"], "reading_value": breach["reading_value"],
                       "threshold": breach["threshold"], "machine_id": machine_id,
                       "predictive_threat_score": score, "is_quarantined": bool(quarantined)}
            db.conn.execute(
                """INSERT INTO av_correlation_events
                   (event_id, stream_id, zone, event_type, threat_level, source, correlated_machine_id, detail)
                   VALUES (?, NULL, ?, 'sensor_fleet_correlation', ?, 'global_fleet_matrix', ?, ?)""",
                (event_id, zone, threat_level, machine_id, json.dumps(detail, default=str)),
            )
            correlated_events.append({"event_id": event_id, "zone": zone, "threat_level": threat_level, **detail})
    if correlated_events:
        db.conn.commit()
    return {"correlation_timestamp": _now_iso(), "correlated_events": correlated_events,
            "actionable_insights": len(correlated_events)}


# ══════════════════════════════════════════════════════════════════════════
# Fusion / reasoning / response — real composite signals, real capabilities
# engine delegation (never bypasses its approval gate)
# ══════════════════════════════════════════════════════════════════════════

@router.post("/neural/sensory-fusion")
async def sensory_fusion(stream_id: str, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    stream_row = db.conn.execute(
        "SELECT * FROM av_stream_registry WHERE stream_id = ?", (stream_id,)
    ).fetchone()
    if not stream_row:
        raise HTTPException(status_code=404, detail=f"stream {stream_id} not found")
    stream = _row_dict(db, stream_row)
    zone = stream.get("zone")

    sensor_rows = db.conn.execute(
        "SELECT * FROM av_sensor_readings WHERE zone = ? ORDER BY recorded_at DESC LIMIT 20", (zone,)
    ).fetchall() if zone else []
    correlation_rows = db.conn.execute(
        "SELECT * FROM av_correlation_events WHERE stream_id = ? OR zone = ? ORDER BY created_at DESC LIMIT 20",
        (stream_id, zone),
    ).fetchall()

    return {
        "stream": stream,
        "recent_sensor_readings": [_row_dict(db, r) for r in sensor_rows],
        "recent_correlation_events": [_row_dict(db, r) for r in correlation_rows],
        "timestamp": _now_iso(),
    }


@router.post("/neural/threat-reasoning")
async def threat_reasoning(req: ThreatReasoningRequest, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    fleet_rows = db.conn.execute(
        "SELECT machine_id, predictive_threat_score, is_quarantined FROM global_fleet_matrix WHERE network_segment = ?",
        (req.zone,),
    ).fetchall()
    elevated = [r for r in fleet_rows if r[2] or (r[1] or 0) >= _THREAT_SCORE_ALERT]
    breach_count = db.conn.execute(
        """SELECT COUNT(*) FROM av_sensor_readings
           WHERE zone = ? AND threshold IS NOT NULL AND reading_value > threshold""",
        (req.zone,),
    ).fetchone()[0]

    if any(q for _, _, q in fleet_rows):
        recommended_action, rationale = "fleet:isolate_host", "A machine in this zone is already quarantined."
    elif elevated and breach_count:
        recommended_action, rationale = "detect:scan_yara", "Elevated fleet threat score plus a sensor threshold breach in the same zone."
    elif elevated:
        recommended_action, rationale = "detect:process_tree", "Elevated predictive threat score for a machine in this zone."
    elif breach_count:
        recommended_action, rationale = "detect:fetch_pcap", "Sensor threshold breach in this zone with no elevated fleet signal yet."
    else:
        recommended_action, rationale = None, "No elevated fleet-threat or sensor-breach signal currently correlates to this zone."

    return {
        "zone": req.zone, "stream_id": req.stream_id, "machines_in_zone": len(fleet_rows),
        "machines_elevated": len(elevated), "sensor_threshold_breaches": breach_count,
        "recommended_action": recommended_action, "rationale": rationale,
        "candidate_targets": [r[0] for r in elevated], "timestamp": _now_iso(),
    }


@router.post("/neural/response-decision", dependencies=[require_permission("edr:manage")])
async def response_decision(req: ResponseDecisionRequest, request: Request, db: DuckDBManager = Depends(_db),
                             user: dict = Depends(get_authenticated_user)):
    if req.action_id not in _ALLOWED_ACTIONS:
        raise HTTPException(status_code=422, detail=f"action_id must be one of {sorted(_ALLOWED_ACTIONS)}")
    engine = get_capabilities_engine(db)
    payload = {"agent_id": req.target_machine_id, "machine_id": req.target_machine_id,
               "reason": f"av_command_center threat-reasoning recommendation (zone={req.zone})"}
    result = await engine.execute(req.action_id, payload, executor=req.operator_id, approved=False)
    _audit(db, request, user, "response_decision", "requested", req.target_machine_id,
           {"action_id": req.action_id, "zone": req.zone, "engine_result": result})
    return {"action_id": req.action_id, "target_machine_id": req.target_machine_id,
            "engine_result": result, "timestamp": _now_iso()}


@router.post("/command/execute", dependencies=[require_permission("edr:manage")])
async def execute_command(req: CommandExecuteRequest, request: Request, db: DuckDBManager = Depends(_db),
                           user: dict = Depends(get_authenticated_user)):
    if req.action_id not in _ALLOWED_ACTIONS:
        raise HTTPException(status_code=422, detail=f"action_id must be one of {sorted(_ALLOWED_ACTIONS)}")
    engine = get_capabilities_engine(db)
    result = await engine.execute(req.action_id, req.payload, executor=req.operator_id, approved=False)
    _audit(db, request, user, "command_execute", "requested", req.stream_id or "",
           {"action_id": req.action_id, "engine_result": result})
    return {"action_id": req.action_id, "stream_id": req.stream_id, "engine_result": result, "timestamp": _now_iso()}


# ══════════════════════════════════════════════════════════════════════════
# WebSocket — pushes real correlation events for the stream, not an echo
# ══════════════════════════════════════════════════════════════════════════

@router.websocket("/ws/av-stream/{stream_id}")
async def websocket_av_stream(websocket: WebSocket, stream_id: str):
    await websocket.accept()
    db = get_db_manager()
    _ensure_schema(db)
    try:
        while True:
            await websocket.receive_text()
            rows = db.conn.execute(
                "SELECT * FROM av_correlation_events WHERE stream_id = ? ORDER BY created_at DESC LIMIT 5",
                (stream_id,),
            ).fetchall()
            cols = [d[0] for d in db.conn.description]
            events = [dict(zip(cols, r)) for r in rows]
            await websocket.send_json({
                "stream_id": stream_id, "correlation_events": events,
                "timestamp": _now_iso(),
            })
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("av-stream websocket error for %s", stream_id)
