"""
backend/routers/wireless.py
============================
Wireless (802.11 Wi-Fi) assessment API router (JAKAL v2.3).

Two halves, matching the split used everywhere else in this codebase:
  - WirelessAgent  -> passive/read-only recon (GET-safe, no packets to clients)
  - AIPPayloadGenerator's "wireless" phase -> MITRE-tagged structured
    commands for human review (POST /aip/generate {"phase": "wireless"})

Endpoints:
  GET   /wireless/status         — agent + interface availability
  POST  /wireless/scan           — passive wireless survey for a target site
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status as http_status
from pydantic import BaseModel

try:
    from security_agents.wireless_agent import WirelessAgent
    from database import DuckDBManager, get_db_manager
    _db: Optional[DuckDBManager] = get_db_manager()
    _wireless_agent = WirelessAgent(db_manager=_db)
    WIRELESS_OK = True
except Exception as _e:
    WIRELESS_OK = False
    _WIRELESS_ERR = str(_e)
    _wireless_agent = None

try:
    from tools.authorization import AuthorizationError
except Exception:
    class AuthorizationError(Exception):
        pass


class WirelessScanRequest(BaseModel):
    target: str
    interface: Optional[str] = None
    operator_id: str = "system"


router = APIRouter(prefix="/wireless", tags=["wireless-assessment"])


def _require():
    if not WIRELESS_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Wireless agent unavailable: {_WIRELESS_ERR}")


@router.get("/status")
def wireless_status():
    """Report whether the wireless agent + at least one NIC are available."""
    _require()
    interfaces = _wireless_agent._list_interfaces()
    return {
        "agent_available": True,
        "interfaces_detected": interfaces,
        "note": "Passive scan only. Active wireless payloads (deauth, WPS, evil-twin, "
                "handshake capture) come from POST /api/aip/generate {\"phase\": \"wireless\"} "
                "as human-reviewed commands, never auto-executed.",
    }


@router.post("/scan", status_code=http_status.HTTP_201_CREATED)
def wireless_scan(req: WirelessScanRequest):
    """Passive survey of nearby wireless networks for an authorized site/target."""
    _require()
    try:
        return _wireless_agent.scan(
            target=req.target, interface=req.interface, operator_id=req.operator_id,
        )
    except AuthorizationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
