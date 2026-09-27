"""
backend/routers/settings_dev.py
================================
Developer / System operator settings (JAKAL feature branch).

Endpoints:
  GET  /settings/developer          — current developer settings snapshot
  PUT  /settings/developer          — update telemetry / debug / PQC profile
  WS   /settings/developer/debug    — live debug log stream (operator-only)

These knobs are intentionally separate from the resonance automation-settings
(policy) table: they are process-level / deployment-level preferences, not
per-tenant containment policy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings-developer"])

_STATE: Dict[str, Any] = {
    "telemetry_enabled": True,
    "debug_log_enabled": False,
    "pqc_profile": os.getenv("PQC_PROFILE", "commercial"),
    "updated_at": None,
    "updated_by": None,
}

_VALID_PQC = {"commercial", "cnsa2"}
_DEBUG_SUBSCRIBERS: List[WebSocket] = []
_DEBUG_RING: List[str] = []
_DEBUG_RING_MAX = 200


class DeveloperSettingsUpdate(BaseModel):
    telemetry_enabled: Optional[bool] = None
    debug_log_enabled: Optional[bool] = None
    pqc_profile: Optional[str] = Field(default=None, pattern=r"^(commercial|cnsa2)$")


def _snapshot() -> Dict[str, Any]:
    return {
        "telemetry_enabled": bool(_STATE["telemetry_enabled"]),
        "debug_log_enabled": bool(_STATE["debug_log_enabled"]),
        "pqc_profile": _STATE["pqc_profile"],
        "pqc_profiles_available": sorted(_VALID_PQC),
        "updated_at": _STATE.get("updated_at"),
        "updated_by": _STATE.get("updated_by"),
        "note": (
            "pqc_profile is also driven by the PQC_PROFILE env var; "
            "a process restart is required for crypto modules to fully "
            "re-bind after a profile change."
        ),
    }


def push_debug_line(line: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    entry = f"[{ts}] {line}"
    _DEBUG_RING.append(entry)
    if len(_DEBUG_RING) > _DEBUG_RING_MAX:
        del _DEBUG_RING[: len(_DEBUG_RING) - _DEBUG_RING_MAX]
    dead: List[WebSocket] = []
    for ws in _DEBUG_SUBSCRIBERS:
        try:
            asyncio.get_event_loop().create_task(ws.send_text(entry))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _DEBUG_SUBSCRIBERS:
            _DEBUG_SUBSCRIBERS.remove(ws)


@router.get("/developer")
async def get_developer_settings(user: dict = Depends(get_authenticated_user)):
    return _snapshot()


@router.put("/developer", dependencies=[require_permission("system:*")])
async def put_developer_settings(
    body: DeveloperSettingsUpdate,
    request: Request,
    user: dict = Depends(get_authenticated_user),
):
    changed: Dict[str, Any] = {}
    if body.telemetry_enabled is not None:
        _STATE["telemetry_enabled"] = bool(body.telemetry_enabled)
        changed["telemetry_enabled"] = _STATE["telemetry_enabled"]
    if body.debug_log_enabled is not None:
        _STATE["debug_log_enabled"] = bool(body.debug_log_enabled)
        changed["debug_log_enabled"] = _STATE["debug_log_enabled"]
    if body.pqc_profile is not None:
        if body.pqc_profile not in _VALID_PQC:
            raise HTTPException(status_code=400, detail=f"pqc_profile must be one of {_VALID_PQC}")
        _STATE["pqc_profile"] = body.pqc_profile
        os.environ["PQC_PROFILE"] = body.pqc_profile
        changed["pqc_profile"] = body.pqc_profile

    _STATE["updated_at"] = datetime.now(timezone.utc).isoformat()
    _STATE["updated_by"] = user.get("username")
    push_debug_line(f"developer settings updated by {user.get('username')}: {json.dumps(changed)}")
    logger.info("developer settings updated by %s: %s", user.get("username"), changed)
    return _snapshot()


@router.websocket("/developer/debug")
async def debug_log_ws(websocket: WebSocket):
    await websocket.accept()
    _DEBUG_SUBSCRIBERS.append(websocket)
    try:
        for line in list(_DEBUG_RING):
            await websocket.send_text(line)
        await websocket.send_text("[debug stream connected]")
        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() in ("ping", "keepalive"):
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("debug websocket error")
    finally:
        if websocket in _DEBUG_SUBSCRIBERS:
            _DEBUG_SUBSCRIBERS.remove(websocket)
