"""
backend/routers/awareness.py
==============================
Human Layer Security — Awareness Training + Phishing Campaigns (JAKAL v2.6).

Backs `admin_security_training` and `admin_phishing_sim`. Seeds a small
real curriculum (module keys/titles only — hosting actual course content
is out of scope here, `content_url` is the extension point for an LMS)
and a phishing-template library, then tracks completions / click-through
rates against real DuckDB tables instead of the frontend's hardcoded
percentages.

Endpoints:
  GET  /awareness/training/modules
  POST /awareness/training/modules/{module_key}/complete
  GET  /awareness/training/stats

  GET  /awareness/phishing/templates
  POST /awareness/phishing/campaigns
  GET  /awareness/phishing/campaigns
  GET  /awareness/phishing/campaigns/{campaign_id}/stats
  POST /awareness/phishing/campaigns/{campaign_id}/targets/{email}/opened
  POST /awareness/phishing/campaigns/{campaign_id}/targets/{email}/clicked
  POST /awareness/phishing/campaigns/{campaign_id}/targets/{email}/reported

Ethics/authorization note: simulated phishing must only ever target an
organization's own staff with informed leadership sign-off (this is the
same authorization posture the rest of this platform already enforces
for network-facing actions via tools/authorization.py) — this module
does not send real email; `launch_campaign` records intent/targets for
an operator's own mailer/GoPhish-style integration to consume, it does
not perform delivery itself.
"""

from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

try:
    from database import get_db_manager
    _db = get_db_manager()
    AWARENESS_OK = True
    _ERR = None
except Exception as _e:  # noqa: BLE001
    AWARENESS_OK = False
    _ERR = str(_e)
    _db = None

from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/awareness", tags=["awareness"])

_DEFAULT_MODULES = [
    ("phishing-101", "Recognizing Phishing & Business Email Compromise", "phishing", 15, 80),
    ("password-hygiene", "Password Hygiene & Passphrase Best Practices (NIST SP 800-63B)", "password_hygiene", 10, 80),
    ("social-engineering", "Social Engineering & Pretexting Defense", "social_engineering", 15, 80),
    ("data-handling", "Handling Sensitive Data & Trade Secrets", "data_handling", 10, 80),
    ("incident-reporting", "Reporting Suspicious Activity — When & How", "incident_response", 5, 80),
    ("mfa-and-devices", "MFA, Device Hygiene & Remote Access", "account_security", 10, 80),
]

_PHISHING_TEMPLATES = {
    "it-password-reset": "Urgent: Your password expires today (credential harvesting pretext)",
    "hr-benefits": "Open enrollment ends Friday (link-click pretext)",
    "exec-wire-request": "Quick favor — approve this wire (BEC/CEO-fraud pretext)",
    "shipping-notice": "Your package could not be delivered (attachment pretext)",
}


def _require():
    if not AWARENESS_OK:
        raise HTTPException(status_code=503, detail=f"Awareness module unavailable: {_ERR}")


def _seed():
    if not AWARENESS_OK:
        return
    for key, title, category, minutes, passing in _DEFAULT_MODULES:
        _db.training_seed_module(key, title, category, minutes, passing)


_seed()


def _audit(request: Request, user: dict, action: str, outcome: str, resource_id: str = "", detail=None):
    try:
        _db.insert_audit_entry({
            "actor_user_id": user["user_id"], "actor_label": user["username"],
            "action": action, "resource_type": "awareness", "resource_id": resource_id,
            "outcome": outcome, "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("audit write failed for %s", action)


class CompleteModuleRequest(BaseModel):
    score: int = Field(..., ge=0, le=100)


class CampaignCreateRequest(BaseModel):
    name: str = Field(..., max_length=200)
    template_key: str
    targets: List[EmailStr] = Field(..., min_length=1, max_length=5000)


# ══════════════════════════════════════════════════════════════════════════
# Training
# ══════════════════════════════════════════════════════════════════════════

@router.get("/training/modules")
async def list_modules():
    _require()
    return {"modules": _db.training_list_modules()}


@router.post("/training/modules/{module_key}/complete")
async def complete_module(module_key: str, req: CompleteModuleRequest, request: Request,
                           user: dict = Depends(get_authenticated_user)):
    _require()
    modules = {m["module_key"] for m in _db.training_list_modules()}
    if module_key not in modules:
        raise HTTPException(status_code=404, detail="Unknown training module")
    passed = req.score >= 80
    completion_id = str(uuid.uuid4())
    _db.training_record_completion(completion_id, module_key, user["user_id"], req.score, passed)
    _audit(request, user, "training_complete", "success", module_key, {"score": req.score, "passed": passed})
    return {"completion_id": completion_id, "passed": passed, "score": req.score}


@router.get("/training/stats", dependencies=[require_permission("awareness:manage")])
async def training_stats():
    _require()
    return _db.training_completion_stats()


# ══════════════════════════════════════════════════════════════════════════
# Phishing campaigns
# ══════════════════════════════════════════════════════════════════════════

@router.get("/phishing/templates")
async def list_templates():
    return {"templates": [{"key": k, "description": v} for k, v in _PHISHING_TEMPLATES.items()]}


@router.post("/phishing/campaigns", dependencies=[require_permission("awareness:manage")])
async def create_campaign(req: CampaignCreateRequest, request: Request,
                           user: dict = Depends(get_authenticated_user)):
    _require()
    if req.template_key not in _PHISHING_TEMPLATES:
        raise HTTPException(status_code=422, detail=f"Unknown template_key. Choose from: {list(_PHISHING_TEMPLATES)}")
    campaign_id = str(uuid.uuid4())
    _db.phishing_create_campaign(campaign_id, req.name, req.template_key, user["user_id"],
                                  [str(t) for t in req.targets])
    _audit(request, user, "phishing_campaign_create", "success", campaign_id,
           {"targets": len(req.targets), "template": req.template_key})
    return {"campaign_id": campaign_id, "status": "active", "targets": len(req.targets)}


@router.get("/phishing/campaigns")
async def list_campaigns():
    _require()
    return {"campaigns": _db.phishing_list_campaigns()}


@router.get("/phishing/campaigns/{campaign_id}/stats")
async def campaign_stats(campaign_id: str):
    _require()
    return _db.phishing_campaign_stats(campaign_id)


def _mark_target(campaign_id: str, email: str, column: str):
    row = _db.conn.execute(
        "SELECT 1 FROM phishing_targets WHERE campaign_id = ? AND target_email = ?",
        (campaign_id, email),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Target not found in this campaign")
    _db.conn.execute(
        f"UPDATE phishing_targets SET {column} = now() WHERE campaign_id = ? AND target_email = ?",
        (campaign_id, email),
    )
    _db.conn.commit()


@router.post("/phishing/campaigns/{campaign_id}/targets/{email}/opened")
async def mark_opened(campaign_id: str, email: str):
    _require()
    _mark_target(campaign_id, email, "opened_at")
    return {"status": "recorded", "event": "opened"}


@router.post("/phishing/campaigns/{campaign_id}/targets/{email}/clicked")
async def mark_clicked(campaign_id: str, email: str):
    _require()
    _mark_target(campaign_id, email, "clicked_at")
    return {"status": "recorded", "event": "clicked"}


@router.post("/phishing/campaigns/{campaign_id}/targets/{email}/reported")
async def mark_reported(campaign_id: str, email: str):
    """The GOOD outcome — the target recognized and reported the simulated phish."""
    _require()
    _mark_target(campaign_id, email, "reported_at")
    return {"status": "recorded", "event": "reported"}
