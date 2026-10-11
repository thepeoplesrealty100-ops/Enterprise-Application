"""
backend/routers/fleet_management.py
===================================
Fleet Management & RMM — JAKAL.

Device inventory is served from `network_map`, the same table
routers/ui_bridge.py's GET /api/dashboard/fleet (what the operator
dashboard actually calls) already reads. There is deliberately no
second device table: a parallel inventory is how the two diverging
"fleet" views got here in the first place.

What this platform honestly has, and does not have:

  - It HAS real discovered-host inventory (network_map, populated by the
    recon/enum agents): addresses, hostnames, OS fingerprints, open
    ports, risk scores, last-seen timestamps.
  - It does NOT have an RMM agent installed on managed endpoints. So
    there is no live CPU/memory/disk telemetry, no installed-software
    inventory, no logged-in-user session data, and no way to actually
    push a patch or restart a machine. Endpoints that would need one
    report `not_configured` rather than returning invented numbers --
    they previously returned hardcoded fixtures that looked like
    success.

Containment actions (isolating a device) are NOT executed here. They
are staged through the same human approval gate that
routers/response.py's POST /response/isolate-host uses, for the same
reason given in that module: this platform does not control the
target's network fabric, so an approved isolation is the authorization
record a real firewall/EDR integration or on-call operator acts on.
The previous implementation of POST /actions/isolate-device took no
authentication, created no approval request, wrote no audit entry, and
returned {"isolation_active": true, "network_access_blocked": true} --
claiming a containment that never happened.

Endpoints:
  GET  /api/fleet/devices                  — real inventory, filterable
  GET  /api/fleet/devices/{id}             — one device, real fields only
  GET  /api/fleet/devices/{id}/health      — posture from real signals
  GET  /api/fleet/groups                   — groups derived from real tags
  POST /api/fleet/actions/isolate-device   — staged via approval gate
  POST /api/fleet/actions/*                — not_configured (needs an agent)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fleet", tags=["Fleet Management"])

try:
    from database import get_db_manager
    from wrappers.base import sanitize_target
    from tools.authorization import check_authorization_and_scope, AuthorizationError
    _db = get_db_manager()
    FLEET_OK = True
    _ERR: Optional[str] = None
except Exception as _e:  # noqa: BLE001
    FLEET_OK = False
    _ERR = str(_e)
    _db = None

from dependencies import get_authenticated_user, require_permission


def _require() -> None:
    if not FLEET_OK:
        raise HTTPException(status_code=503, detail=f"Fleet management unavailable: {_ERR}")


# ============================================================================
# MODELS
# ============================================================================

class DeviceOS(str, Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    IOS = "ios"
    ANDROID = "android"
    UNKNOWN = "unknown"


class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class Device(BaseModel):
    device_id: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    device_type: str = "unknown"
    os: DeviceOS = DeviceOS.UNKNOWN
    os_fingerprint: Optional[str] = None
    status: DeviceStatus = DeviceStatus.UNKNOWN
    risk_score: float = 0.0
    open_port_count: int = 0
    tags: List[str] = []
    last_seen: Optional[datetime] = None
    discovered_at: Optional[datetime] = None
    is_quarantined: bool = False


class IsolateDeviceRequest(BaseModel):
    device_id: str
    reason: str


# How long since last_seen before a host is treated as offline. network_map
# rows are written by the recon/enum agents, so "last seen" means "last
# observed by a scan", not an agent heartbeat.
_ONLINE_WINDOW = timedelta(hours=24)

# Actions that would require an RMM agent on the endpoint. Kept as routes
# (they are part of this module's published surface) but answered honestly.
_AGENT_REQUIRED_NOTE = (
    "This platform has no RMM agent deployed on managed endpoints, so it "
    "cannot execute this action. Wire a real RMM/EDR integration and route "
    "this endpoint to it. Script execution against JAKAL-owned sandbox "
    "targets is available via /api/scripts (staged through the approval gate)."
)


def _derive_os(fingerprint: Optional[str]) -> DeviceOS:
    fp = (fingerprint or "").lower()
    if "windows" in fp or "microsoft" in fp:
        return DeviceOS.WINDOWS
    if "mac" in fp or "darwin" in fp or "os x" in fp:
        return DeviceOS.MACOS
    if "ios" in fp or "iphone" in fp or "ipad" in fp:
        return DeviceOS.IOS
    if "android" in fp:
        return DeviceOS.ANDROID
    if "linux" in fp or "ubuntu" in fp or "debian" in fp or "centos" in fp or "rhel" in fp:
        return DeviceOS.LINUX
    return DeviceOS.UNKNOWN


def _derive_status(last_seen) -> DeviceStatus:
    if not last_seen:
        return DeviceStatus.UNKNOWN
    if isinstance(last_seen, str):
        try:
            last_seen = datetime.fromisoformat(last_seen)
        except ValueError:
            return DeviceStatus.UNKNOWN
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return DeviceStatus.ONLINE if datetime.now(timezone.utc) - last_seen <= _ONLINE_WINDOW else DeviceStatus.OFFLINE


def _derive_device_type(tags: List[str], os_value: DeviceOS, open_ports: List[Any]) -> str:
    lowered = {str(t).lower() for t in tags}
    for candidate in ("server", "workstation", "router", "firewall", "printer", "iot", "mobile"):
        if candidate in lowered:
            return candidate
    if os_value in (DeviceOS.IOS, DeviceOS.ANDROID):
        return "mobile"
    # A host serving web/db/ssh ports is far more likely a server than a desk
    # machine. Only a heuristic -- reported as such, never as ground truth.
    server_ports = {22, 80, 443, 3306, 5432, 1433, 8080}
    for p in open_ports or []:
        port_num = p.get("port") if isinstance(p, dict) else p
        try:
            if int(port_num) in server_ports:
                return "server"
        except (TypeError, ValueError):
            continue
    return "unknown"


def _loads(raw, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _quarantined_ids() -> set:
    """is_quarantined lives on global_fleet_matrix (resonance posture),
    keyed by machine_id. Best-effort join -- absence just means no
    quarantine flag is known for that host."""
    try:
        rows = _db.query("SELECT machine_id FROM global_fleet_matrix WHERE is_quarantined = true")
        return {str(r[0]) for r in (rows or [])}
    except Exception:
        logger.debug("global_fleet_matrix quarantine lookup skipped", exc_info=True)
        return set()


def _row_to_device(row, quarantined: set) -> Device:
    (device_id, hostname, ip_address, mac_address, os_fp,
     open_ports_raw, tags_raw, risk_score, last_seen, discovered_at) = row
    tags = _loads(tags_raw, [])
    open_ports = _loads(open_ports_raw, [])
    os_value = _derive_os(os_fp)
    return Device(
        device_id=str(device_id),
        hostname=hostname,
        ip_address=ip_address,
        mac_address=mac_address,
        device_type=_derive_device_type(tags, os_value, open_ports),
        os=os_value,
        os_fingerprint=os_fp,
        status=_derive_status(last_seen),
        risk_score=float(risk_score or 0.0),
        open_port_count=len(open_ports) if isinstance(open_ports, list) else 0,
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        last_seen=last_seen,
        discovered_at=discovered_at,
        is_quarantined=(str(device_id) in quarantined or str(ip_address) in quarantined
                        or str(hostname) in quarantined),
    )


_SELECT_COLS = """id, hostname, ip_address, mac_address, os_fingerprint,
                  open_ports, tags, risk_score, last_seen, discovered_at"""


# ============================================================================
# INVENTORY (real data)
# ============================================================================

@router.get("/devices")
async def get_fleet_devices(
    status: Optional[DeviceStatus] = None,
    os: Optional[DeviceOS] = None,
    risk_min: Optional[float] = None,
    risk_max: Optional[float] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """
    Real device inventory from network_map (hosts discovered by the recon
    and enumeration agents).

    `status` and `os` are derived values, not stored columns, so they are
    filtered after the row fetch; `risk_min`/`risk_max` filter in SQL.
    """
    _require()
    where, params = ["1=1"], []
    if risk_min is not None:
        where.append("risk_score >= ?")
        params.append(risk_min)
    if risk_max is not None:
        where.append("risk_score <= ?")
        params.append(risk_max)
    clause = " AND ".join(where)

    try:
        rows = _db.query(
            f"SELECT {_SELECT_COLS} FROM network_map WHERE {clause} "
            f"ORDER BY risk_score DESC, last_seen DESC LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        )
        total = (_db.query(f"SELECT COUNT(*) FROM network_map WHERE {clause}", tuple(params)) or [[0]])[0][0]
    except Exception as e:
        logger.exception("Fleet inventory query failed")
        raise HTTPException(status_code=500, detail=f"Fleet inventory query failed: {e}")

    quarantined = _quarantined_ids()
    devices = [_row_to_device(r, quarantined) for r in (rows or [])]
    if status is not None:
        devices = [d for d in devices if d.status == status]
    if os is not None:
        devices = [d for d in devices if d.os == os]

    return {
        "devices": devices,
        "returned": len(devices),
        "total_in_inventory": int(total or 0),
        "source": "network_map",
        "note": (
            "Inventory is discovered hosts, not agent-enrolled endpoints. "
            "'status' is derived from last_seen (online = observed within "
            f"{int(_ONLINE_WINDOW.total_seconds() // 3600)}h), and 'device_type' "
            "is a heuristic from tags/open ports."
        ),
    }


@router.get("/devices/{device_id}")
async def get_device_details(device_id: str) -> Dict[str, Any]:
    """One device. Returns only fields this platform actually observes."""
    _require()
    try:
        rows = _db.query(
            f"SELECT {_SELECT_COLS}, notes, pentest_id FROM network_map WHERE id = ?",
            (device_id,),
        )
    except Exception as e:
        logger.exception("Device lookup failed")
        raise HTTPException(status_code=500, detail=f"Device lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="Device not found in inventory")

    row = rows[0]
    device = _row_to_device(row[:10], _quarantined_ids())
    open_ports = _loads(row[5], [])
    return {
        "device": device,
        "open_ports": open_ports,
        "notes": row[10],
        "pentest_id": row[11],
        "unavailable": {
            "reason": _AGENT_REQUIRED_NOTE,
            "fields": [
                "cpu/memory/disk utilization", "installed applications",
                "running processes", "logged-in user", "antivirus/firewall state",
            ],
        },
    }


@router.get("/devices/{device_id}/health")
async def get_device_health(device_id: str) -> Dict[str, Any]:
    """
    Security posture for one device, computed from signals this platform
    genuinely has: risk score, exposed ports, scan recency, quarantine
    flag. This is NOT host health (CPU/RAM/disk) -- that needs an agent.
    """
    _require()
    try:
        rows = _db.query(
            f"SELECT {_SELECT_COLS} FROM network_map WHERE id = ?", (device_id,)
        )
    except Exception as e:
        logger.exception("Device health query failed")
        raise HTTPException(status_code=500, detail=f"Device health query failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="Device not found in inventory")

    device = _row_to_device(rows[0], _quarantined_ids())
    checks = [
        {"check": "Recently observed", "status": "pass" if device.status == DeviceStatus.ONLINE else "warn",
         "detail": f"last_seen={device.last_seen}"},
        {"check": "Risk score within tolerance", "status": "pass" if device.risk_score < 7.0 else "fail",
         "detail": f"risk_score={device.risk_score}"},
        {"check": "Exposed port count", "status": "pass" if device.open_port_count <= 10 else "warn",
         "detail": f"open_ports={device.open_port_count}"},
        {"check": "Not quarantined", "status": "fail" if device.is_quarantined else "pass",
         "detail": f"is_quarantined={device.is_quarantined}"},
    ]
    failed = sum(1 for c in checks if c["status"] == "fail")
    warned = sum(1 for c in checks if c["status"] == "warn")
    posture = "at_risk" if failed else ("degraded" if warned else "healthy")
    return {
        "device_id": device.device_id,
        "posture": posture,
        "posture_score": round(max(0.0, 1.0 - (failed * 0.34) - (warned * 0.12)), 2),
        "checks": checks,
        "host_telemetry": {"available": False, "reason": _AGENT_REQUIRED_NOTE},
    }


@router.get("/groups")
async def get_device_groups() -> Dict[str, Any]:
    """Device groups derived from the tags actually present in inventory."""
    _require()
    try:
        rows = _db.query("SELECT tags FROM network_map")
    except Exception as e:
        logger.exception("Group derivation failed")
        raise HTTPException(status_code=500, detail=f"Group derivation failed: {e}")

    counts: Dict[str, int] = {}
    for (tags_raw,) in (rows or []):
        for tag in _loads(tags_raw, []):
            counts[str(tag)] = counts.get(str(tag), 0) + 1
    groups = [{"group_id": f"tag:{t}", "name": t, "device_count": c}
              for t, c in sorted(counts.items(), key=lambda kv: -kv[1])]
    return {
        "groups": groups,
        "total_groups": len(groups),
        "note": "Groups are derived from network_map tags. Policy objects are "
                "not modeled in this platform; there is no group-policy engine to apply.",
    }


# ============================================================================
# CONTAINMENT — staged through the human approval gate, never auto-executed
# ============================================================================

@router.post("/actions/isolate-device", dependencies=[require_permission("response:manage")])
async def isolate_device(req: IsolateDeviceRequest, request: Request,
                          user: dict = Depends(get_authenticated_user)) -> Dict[str, Any]:
    """
    Stage a device isolation for human approval. Never executes on its own.

    Deliberately mirrors POST /api/response/isolate-host rather than
    reimplementing containment: same approval_requests flow, same
    action_type ("isolate_host_staged"), so an approved request is
    enforceable by the same already-hardened path
    (routers/response.py's /actions/{id}/enforce ->
    HardenedEnforcementOrchestrator, which applies the compliance gate
    and retry policy).
    """
    _require()
    try:
        rows = _db.query("SELECT ip_address, hostname FROM network_map WHERE id = ?", (req.device_id,))
    except Exception as e:
        logger.exception("Device lookup failed during isolation staging")
        raise HTTPException(status_code=500, detail=f"Device lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="Device not found in inventory")

    # Prefer the IP, not the hostname: authorized scope is defined in CIDRs
    # (tools/authorization.py), so an IP is the only form of this target
    # that can actually be validated against it. Targeting the hostname
    # would put the containment request outside what scope enforcement can
    # reason about.
    target = rows[0][0] or rows[0][1]
    if not target:
        raise HTTPException(status_code=422, detail="Device has neither IP nor hostname to target")

    try:
        sanitize_target(target)
        check_authorization_and_scope(target, "isolate_host", user["username"], db=_db)
    except (ValueError, AuthorizationError) as e:
        raise HTTPException(status_code=403, detail=str(e))

    request_id = str(uuid.uuid4())
    _db.create_approval_request({
        "request_id": request_id,
        "requested_by": user["username"],
        "action_type": "isolate_host_staged",
        "target": target,
        "phase": "containment",
        "risk_level": "HIGH",
        "summary": f"Device isolation requested from fleet management: {req.reason}",
        "payload_detail": {
            "target": target, "reason": req.reason, "device_id": req.device_id,
            "d3fend_technique": "D3-NI", "origin": "fleet_management",
        },
        "origin_module": "fleet_management_router",
    })

    action_id = str(uuid.uuid4())
    try:
        _db.insert_remediation_action({
            "action_id": action_id, "action_type": "isolate_host_staged",
            "target": target, "status": "staged", "risk_level": "HIGH",
            "approval_request_id": request_id, "operator_id": user["username"],
            "d3fend_technique": "D3-NI",
            "detail": {"reason": req.reason, "device_id": req.device_id, "origin": "fleet_management"},
        })
    except Exception:
        logger.warning("remediation_actions write failed for staged isolation %s", action_id, exc_info=True)

    return {
        "action_id": action_id,
        "status": "staged",
        "isolation_active": False,
        "approval_request_id": request_id,
        "device_id": req.device_id,
        "target": target,
        "d3fend_technique": "D3-NI",
        "note": "Staged only. Approve at POST /api/approval/{id}/approve, then enforce "
                "at POST /api/response/actions/{approval_request_id}/enforce. Nothing "
                "on the target's network has changed.",
    }


# ============================================================================
# AGENT-DEPENDENT ACTIONS — honest not_configured instead of fabricated success
# ============================================================================

def _not_configured(action: str, **echo) -> Dict[str, Any]:
    return {"action_type": action, "status": "not_configured",
            "executed": False, "reason": _AGENT_REQUIRED_NOTE, **echo}


@router.post("/actions/run-script", dependencies=[require_permission("response:manage")])
async def run_script(device_ids: List[str], script_id: str,
                      user: dict = Depends(get_authenticated_user)):
    _require()
    return _not_configured("run_script", script_id=script_id, target_devices=len(device_ids),
                           alternative="POST /api/scripts/stage")


@router.post("/actions/restart-devices", dependencies=[require_permission("response:manage")])
async def restart_devices(device_ids: List[str], user: dict = Depends(get_authenticated_user)):
    _require()
    return _not_configured("restart_devices", target_devices=len(device_ids))


@router.post("/actions/update-policy", dependencies=[require_permission("response:manage")])
async def update_policy(device_ids: List[str], policy_id: str,
                         user: dict = Depends(get_authenticated_user)):
    _require()
    return _not_configured("update_policy", policy_id=policy_id, target_devices=len(device_ids))


@router.post("/actions/deploy-patch", dependencies=[require_permission("response:manage")])
async def deploy_patch(device_ids: List[str], patch_id: str,
                        user: dict = Depends(get_authenticated_user)):
    _require()
    return _not_configured("deploy_patch", patch_id=patch_id, target_devices=len(device_ids))


@router.post("/bulk/execute", dependencies=[require_permission("response:manage")])
async def bulk_execute(action_type: str, target_query: Dict[str, Any],
                        user: dict = Depends(get_authenticated_user)):
    _require()
    return _not_configured("bulk_execute", requested_action=action_type, query=target_query)


@router.post("/groups/{group_id}/apply-policy", dependencies=[require_permission("response:manage")])
async def apply_group_policy(group_id: str, policy_id: str,
                              user: dict = Depends(get_authenticated_user)):
    _require()
    return _not_configured("apply_group_policy", group_id=group_id, policy_id=policy_id)
