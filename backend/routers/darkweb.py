"""
backend/routers/darkweb.py
============================
Dark Web Monitoring — JAKAL v2.6.

Replaces the frontend's `admin_dark_web` mock page's implicit "we're
scanning the dark web" framing with an honest, pluggable connector
architecture:

  - A watchlist of identifiers (emails/domains) an operator wants monitored.
  - A `ThreatIntelConnector` interface (below) that any breach/leak feed
    can implement.
  - ONE real connector wired in: Have I Been Pwned (HIBP) v3, the
    industry-standard breach-notification API also used by browsers
    (Firefox Monitor, Chrome password checkup use the same underlying
    corpus). Checking a *specific* account requires a paid HIBP API key
    (haveibeenpwned.com/API/Key) — this is HIBP's own anti-abuse
    requirement, not a limitation of this code — configured via
    HIBP_API_KEY. Without a key, `/darkweb/scan` returns a clear
    "connector not configured" result rather than fabricating findings.
  - The `manual` source lets an analyst record a finding from a paid feed
    this deployment doesn't have API access to yet (Recorded Future,
    SpyCloud, Flashpoint, Intel 471, DarkOwl — genuine dark-web-monitoring
    vendors) — same table, so the UI doesn't need to know the difference.

This is the honest state of "dark web monitoring" without a paid feed
contract: real breach-corpus lookups via HIBP once a key is configured,
plus a structured place to log findings from whichever paid vendor an
organization actually contracts with.

Endpoints:
  POST /darkweb/watchlist            — add an identifier to monitor
  GET  /darkweb/watchlist            — list the watchlist
  POST /darkweb/scan                 — run HIBP checks for every watched email
  GET  /darkweb/findings             — list findings
  POST /darkweb/findings/manual      — record a finding from an external feed
  POST /darkweb/findings/{finding_id}/acknowledge
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

try:
    from database import get_db_manager
    _db = get_db_manager()
    DARKWEB_OK = True
    _ERR = None
except Exception as _e:  # noqa: BLE001
    DARKWEB_OK = False
    _ERR = str(_e)
    _db = None

from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/darkweb", tags=["darkweb"])

_HIBP_BASE = "https://haveibeenpwned.com/api/v3"


def _require():
    if not DARKWEB_OK:
        raise HTTPException(status_code=503, detail=f"Dark web module unavailable: {_ERR}")


def _audit(request: Request, user: dict, action: str, outcome: str, resource_id: str = "", detail=None):
    try:
        _db.insert_audit_entry({
            "actor_user_id": user["user_id"], "actor_label": user["username"],
            "action": action, "resource_type": "darkweb", "resource_id": resource_id,
            "outcome": outcome, "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("audit write failed for %s", action)


class WatchlistAddRequest(BaseModel):
    identifier: str = Field(..., max_length=256)
    identifier_type: str = Field(default="email", pattern="^(email|domain)$")


class ManualFindingRequest(BaseModel):
    watch_id: str
    source: str = Field(..., max_length=64, description="e.g. recorded_future, spycloud, flashpoint, manual")
    breach_name: Optional[str] = None
    breach_date: Optional[str] = None
    data_classes: List[str] = Field(default_factory=list)
    severity: str = Field(default="MEDIUM")


def _hibp_check_account(email: str) -> dict:
    """Real HIBP v3 lookup. Requires HIBP_API_KEY (paid tier — HIBP's own requirement)."""
    api_key = os.getenv("HIBP_API_KEY", "")
    if not api_key:
        return {"configured": False, "breaches": [], "note": "Set HIBP_API_KEY to enable live breach checks."}
    try:
        resp = requests.get(
            f"{_HIBP_BASE}/breachedaccount/{email}",
            headers={"hibp-api-key": api_key, "user-agent": "JAKAL-DarkWebMonitor"},
            params={"truncateResponse": "false"},
            timeout=10,
        )
        if resp.status_code == 404:
            return {"configured": True, "breaches": []}  # no breaches found — good news
        resp.raise_for_status()
        return {"configured": True, "breaches": resp.json()}
    except requests.RequestException as e:
        logger.warning("HIBP lookup failed for watched identifier: %s", e)
        return {"configured": True, "breaches": [], "error": str(e)}


@router.post("/watchlist", dependencies=[require_permission("darkweb:manage")])
async def add_watch(req: WatchlistAddRequest, request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    watch_id = str(uuid.uuid4())
    _db.darkweb_add_watch(watch_id, req.identifier, req.identifier_type, user["user_id"])
    _audit(request, user, "darkweb_watch_add", "success", watch_id, {"identifier": req.identifier})
    return {"watch_id": watch_id, "status": "watching"}


@router.get("/watchlist")
async def list_watch():
    _require()
    return {"watchlist": _db.darkweb_list_watch()}


@router.post("/scan", dependencies=[require_permission("darkweb:manage")])
async def run_scan(request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    watchlist = [w for w in _db.darkweb_list_watch() if w["identifier_type"] == "email"]
    new_findings = 0
    connector_configured = bool(os.getenv("HIBP_API_KEY"))
    for w in watchlist:
        result = _hibp_check_account(w["identifier"])
        _db.darkweb_touch_watch(w["watch_id"])
        for breach in result.get("breaches", []):
            finding_id = str(uuid.uuid4())
            _db.darkweb_insert_finding({
                "finding_id": finding_id, "watch_id": w["watch_id"], "source": "hibp",
                "breach_name": breach.get("Name") or breach.get("Title"),
                "breach_date": breach.get("BreachDate"),
                "data_classes": breach.get("DataClasses", []),
                "severity": "HIGH" if "Passwords" in (breach.get("DataClasses") or []) else "MEDIUM",
            })
            new_findings += 1
    _audit(request, user, "darkweb_scan", "success",
           detail={"watched": len(watchlist), "new_findings": new_findings, "connector_configured": connector_configured})
    return {
        "watched_identifiers": len(watchlist), "new_findings": new_findings,
        "connector": "hibp", "connector_configured": connector_configured,
        "note": None if connector_configured else "HIBP_API_KEY not set — no live connector active; use POST /darkweb/findings/manual to log findings from a contracted feed instead.",
    }


@router.get("/findings")
async def list_findings(watch_id: Optional[str] = None, limit: int = 100):
    _require()
    return {"findings": _db.darkweb_list_findings(watch_id=watch_id, limit=max(1, min(limit, 500)))}


@router.post("/findings/manual", dependencies=[require_permission("darkweb:manage")])
async def record_manual_finding(req: ManualFindingRequest, request: Request,
                                 user: dict = Depends(get_authenticated_user)):
    _require()
    finding_id = str(uuid.uuid4())
    _db.darkweb_insert_finding({
        "finding_id": finding_id, "watch_id": req.watch_id, "source": req.source,
        "breach_name": req.breach_name, "breach_date": req.breach_date,
        "data_classes": req.data_classes, "severity": req.severity,
    })
    _audit(request, user, "darkweb_finding_manual", "success", finding_id, {"source": req.source})
    return {"finding_id": finding_id, "status": "recorded"}


@router.post("/findings/{finding_id}/acknowledge", dependencies=[require_permission("darkweb:manage")])
async def acknowledge_finding(finding_id: str, request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    row = _db.conn.execute("SELECT 1 FROM darkweb_findings WHERE finding_id = ?", (finding_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Finding not found")
    _db.conn.execute("UPDATE darkweb_findings SET acknowledged = true WHERE finding_id = ?", (finding_id,))
    _db.conn.commit()
    _audit(request, user, "darkweb_finding_ack", "success", finding_id)
    return {"status": "acknowledged"}
