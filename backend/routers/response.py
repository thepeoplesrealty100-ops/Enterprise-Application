"""
backend/routers/response.py
=============================
Detection & Response — JAKAL v2.7.

The defensive counterpart to routers/pentest.py's offensive pipeline.
Everything here follows the same safety posture already established by
security_agents/exploit_agent.py and tools/authorization.py: nothing that
claims to touch real infrastructure (isolating a host, quarantining a
host) executes on its own — it is staged as an approval_requests row
(the same table/flow the rest of the platform already uses) and a human
operator decides via the existing POST /api/approval/{id}/approve|deny.
What this router *does* auto-execute are genuinely safe, reversible,
data-layer actions: blocking an indicator (a row in threat_intel) and
recording an artifact quarantine flag — both are "stop trusting this",
never "reach out and touch a machine we don't run".

Grounding:
  - NIST SP 800-61 Rev. 3 (finalized April 2025) maps incident response
    onto NIST CSF 2.0's Detect / Respond / Recover functions — this
    module's action_types are tagged with the CSF 2.0 function they serve.
  - MITRE D3FEND (d3fend.mitre.org) technique IDs are attached where a
    real defensive-technique mapping exists (D3-CQ Content Quarantine,
    D3-NI Network Isolation, D3-EI Execution Isolation, D3-OTF Outbound
    Traffic Filtering for IOC blocking).

Endpoints:
  POST /response/triage              — score a finding, recommend a playbook, auto-stage containment if severe
  POST /response/ioc/block           — real, immediate: adds an indicator to threat_intel
  GET  /response/ioc                 — list active blocked indicators
  POST /response/quarantine          — artifact: immediate data-layer flag. host: staged via approval gate
  POST /response/isolate-host        — always staged via approval gate (never auto-executed)
  GET  /response/actions             — remediation action history
  GET  /response/stats               — counts by type/status
  GET  /response/playbooks/recommend — keyword/category playbook lookup (no side effects)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

try:
    from database import get_db_manager
    from tools.authorization import check_authorization_and_scope, AuthorizationError
    from wrappers.base import sanitize_target
    from threat_scoring import score_recon_finding
    from security_agents.edr_mdr import DEFAULT_PLAYBOOKS
    _db = get_db_manager()
    RESPONSE_OK = True
    _ERR = None
except Exception as _e:  # noqa: BLE001
    RESPONSE_OK = False
    _ERR = str(_e)
    _db = None
    DEFAULT_PLAYBOOKS = []

from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/response", tags=["response"])

# action_type -> (csf2_function, default d3fend_technique)
_ACTION_META = {
    "ioc_block": ("Respond", "D3-OTF"),           # Outbound Traffic Filtering
    "quarantine_artifact": ("Respond", "D3-CQ"),   # Content Quarantine
    "quarantine_host_staged": ("Respond", "D3-EI"),  # Execution Isolation
    "isolate_host_staged": ("Respond", "D3-NI"),   # Network Isolation
    "script_catalog_execution": ("Detect", None),
    "triage": ("Detect", None),
}


def _require():
    if not RESPONSE_OK:
        raise HTTPException(status_code=503, detail=f"Response module unavailable: {_ERR}")


def _pqc_sign(action_type: str, payload: Dict[str, Any], operator_id: str) -> Optional[str]:
    try:
        from crypto.pqc_manager import PQCAuditManager
        pqc = PQCAuditManager()
        signed = pqc.sign_agent_action(agent_id="response-router", action_payload=payload, operator_id=operator_id)
        _db.insert_pqc_audit_entry({
            "entry_id": signed["entry_id"], "agent_id": "response-router",
            "operator_id": operator_id, "action_type": action_type,
            "action_detail": __import__("json").dumps(payload, default=str),
            "payload_hash": signed["payload_hash"], "pqc_signature": signed["pqc_signature"],
            "algorithm": signed["algorithm"], "public_key": signed["public_key"],
        })
        return signed["entry_id"]
    except Exception as e:
        logger.warning("PQC signing unavailable for response action: %s", e)
        return None


def _record_action(action_type: str, target: Optional[str], status: str, risk_level: str,
                    operator_id: str, detail: Dict[str, Any],
                    approval_request_id: Optional[str] = None) -> str:
    action_id = str(uuid.uuid4())
    csf2_function, d3fend = _ACTION_META.get(action_type, (None, None))
    detail = {**detail, "csf2_function": csf2_function}
    _db.insert_remediation_action({
        "action_id": action_id, "action_type": action_type, "target": target,
        "status": status, "risk_level": risk_level, "approval_request_id": approval_request_id,
        "operator_id": operator_id, "d3fend_technique": d3fend, "detail": detail,
    })
    try:
        _db.insert_unified_security_event({
            "event_id": str(uuid.uuid4()), "source_module": "RESPONSE",
            "threat_category": action_type.upper(),
            "severity_score": {"LOW": 0.2, "MEDIUM": 0.5, "HIGH": 0.8, "CRITICAL": 1.0}.get(risk_level, 0.3),
            "raw_payload": {"action_id": action_id, "target": target, **detail},
            "approval_request_id": approval_request_id,
        })
    except Exception:
        logger.debug("unified_security_events write skipped for %s", action_id)
    return action_id


def _audit(request: Request, user: dict, action: str, outcome: str, resource_id: str = "", detail=None):
    try:
        _db.insert_audit_entry({
            "actor_user_id": user["user_id"], "actor_label": user["username"],
            "action": action, "resource_type": "response", "resource_id": resource_id,
            "outcome": outcome, "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("audit write failed for %s", action)


# ══════════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════════

class TriageRequest(BaseModel):
    finding_summary: str = Field(..., max_length=2000)
    threat_category: str = Field(default="")
    target: str = Field(default="")
    operator_id: str = Field(default="system")
    indicators: Dict[str, Any] = Field(default_factory=dict)
    auto_stage_threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class IocBlockRequest(BaseModel):
    indicator: str = Field(..., max_length=512)
    indicator_type: str = Field(default="ip", pattern="^(ip|domain|hash_sha256|url|email)$")
    reason: str = Field(default="", max_length=500)
    confidence: int = Field(default=80, ge=0, le=100)


class QuarantineRequest(BaseModel):
    target: str = Field(..., max_length=256)
    target_type: str = Field(default="artifact", pattern="^(artifact|host)$")
    reason: str = Field(default="", max_length=500)


class IsolateHostRequest(BaseModel):
    target: str = Field(..., max_length=256)
    reason: str = Field(..., max_length=500)


# ══════════════════════════════════════════════════════════════════════════
# Triage — score + recommend, no destructive side effects unless severe
# ══════════════════════════════════════════════════════════════════════════

def _recommend_playbooks(threat_category: str, finding_summary: str) -> List[Dict[str, str]]:
    """Deterministic keyword/category match against the seeded playbook
    library — same explainable-over-opaque philosophy as threat_scoring.py.
    Does not invent playbooks; only ranks the real, existing catalog."""
    text = f"{threat_category} {finding_summary}".lower()
    scored = []
    for pb in DEFAULT_PLAYBOOKS:
        hits = sum(1 for word in pb["key"].split("_") if word in text)
        hits += sum(1 for word in pb["category"].split("_") if word in text)
        if hits > 0 or pb["category"] in text:
            scored.append((hits, pb))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"key": pb["key"], "name": pb["name"], "category": pb["category"]} for _, pb in scored[:3]]


@router.post("/triage")
async def triage(req: TriageRequest, request: Request):
    _require()
    severity = score_recon_finding({
        "finding_summary": req.finding_summary,
        "threat_category": req.threat_category,
        "indicators": req.indicators,
    })
    recommended = _recommend_playbooks(req.threat_category, req.finding_summary)

    staged_request_id = None
    if severity >= req.auto_stage_threshold and recommended:
        staged_request_id = str(uuid.uuid4())
        pqc_entry = _pqc_sign("triage_auto_stage", {
            "target": req.target, "severity": severity, "playbook": recommended[0]["key"],
        }, req.operator_id)
        _db.create_approval_request({
            "request_id": staged_request_id, "requested_by": req.operator_id,
            "action_type": "response_containment", "target": req.target,
            "phase": "containment", "risk_level": "HIGH" if severity >= 0.9 else "MEDIUM",
            "summary": f"Auto-staged from triage (severity={severity}): {recommended[0]['name']}",
            "payload_detail": {
                "finding_summary": req.finding_summary, "threat_category": req.threat_category,
                "severity": severity, "recommended_playbook": recommended[0]["key"],
            },
            "pqc_entry_id": pqc_entry, "origin_module": "response_triage",
        })
    action_id = _record_action(
        "triage", req.target, "staged" if staged_request_id else "completed",
        "HIGH" if severity >= 0.8 else "MEDIUM" if severity >= 0.4 else "LOW",
        req.operator_id,
        {"severity": severity, "recommended_playbooks": recommended, "finding_summary": req.finding_summary},
        approval_request_id=staged_request_id,
    )
    return {
        "action_id": action_id, "severity": severity, "recommended_playbooks": recommended,
        "auto_staged_approval_request_id": staged_request_id,
        "note": ("Severity crossed the auto-stage threshold — a containment approval request was "
                 "created; a human operator must approve it at POST /api/approval/{id}/approve "
                 "before anything further happens.") if staged_request_id else
                "Below auto-stage threshold — recommendation only, no action taken.",
    }


@router.get("/playbooks/recommend")
async def recommend(category: str = "", keyword: str = ""):
    _require()
    return {"recommended": _recommend_playbooks(category, keyword)}


# ══════════════════════════════════════════════════════════════════════════
# IOC blocking — real, immediate, safe (adding a deny-list entry)
# ══════════════════════════════════════════════════════════════════════════

@router.post("/ioc/block", dependencies=[require_permission("response:manage")])
async def block_ioc(req: IocBlockRequest, request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    _db.conn.execute(
        "INSERT INTO threat_intel (feed_source, intel_type, indicator, indicator_type, "
        "confidence, severity, tlp, tags, first_seen, active) "
        "VALUES ('operator_block', 'IOC', ?, ?, ?, ?, 'AMBER', '[\"response_router\"]', now(), true)",
        (req.indicator, req.indicator_type, req.confidence,
         "HIGH" if req.confidence >= 70 else "MEDIUM"),
    )
    _db.conn.commit()
    action_id = _record_action("ioc_block", req.indicator, "completed", "LOW", user["username"],
                                {"reason": req.reason, "indicator_type": req.indicator_type})
    _audit(request, user, "ioc_block", "success", req.indicator, {"reason": req.reason})
    return {"action_id": action_id, "status": "blocked", "indicator": req.indicator}


@router.get("/ioc")
async def list_iocs(limit: int = 100):
    _require()
    rows = _db.conn.execute(
        "SELECT indicator, indicator_type, severity, confidence, first_seen, tlp "
        "FROM threat_intel WHERE feed_source = 'operator_block' AND active = true "
        "ORDER BY first_seen DESC LIMIT ?", (max(1, min(limit, 500)),),
    ).fetchall()
    cols = [d[0] for d in _db.conn.description]
    return {"indicators": [dict(zip(cols, r)) for r in rows]}


# ══════════════════════════════════════════════════════════════════════════
# Quarantine / isolation — artifact is real+immediate; host is always staged
# ══════════════════════════════════════════════════════════════════════════

@router.post("/quarantine", dependencies=[require_permission("response:manage")])
async def quarantine(req: QuarantineRequest, request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    if req.target_type == "artifact":
        action_id = _record_action("quarantine_artifact", req.target, "completed", "LOW",
                                    user["username"], {"reason": req.reason})
        _audit(request, user, "quarantine_artifact", "success", req.target, {"reason": req.reason})
        return {"action_id": action_id, "status": "quarantined", "target": req.target}

    # target_type == "host": this platform doesn't own the target's network
    # fabric (same honest boundary VMOrchestrator's docstring draws) -- so
    # "quarantine a host" can only ever be staged for a human decision /
    # a real EDR/firewall integration to carry out, never auto-executed.
    try:
        sanitize_target(req.target)
        check_authorization_and_scope(req.target, "quarantine_host", user["username"], db=_db)
    except (ValueError, AuthorizationError) as e:
        raise HTTPException(status_code=403, detail=str(e))

    request_id = str(uuid.uuid4())
    pqc_entry = _pqc_sign("quarantine_host_staged", {"target": req.target, "reason": req.reason}, user["username"])
    _db.create_approval_request({
        "request_id": request_id, "requested_by": user["username"],
        "action_type": "quarantine_host_staged", "target": req.target, "phase": "containment",
        "risk_level": "HIGH", "summary": f"Host quarantine requested: {req.reason}",
        "payload_detail": {"target": req.target, "reason": req.reason},
        "pqc_entry_id": pqc_entry, "origin_module": "response_router",
    })
    action_id = _record_action("quarantine_host_staged", req.target, "staged", "HIGH",
                                user["username"], {"reason": req.reason}, approval_request_id=request_id)
    _audit(request, user, "quarantine_host_staged", "success", req.target, {"approval_request_id": request_id})
    return {"action_id": action_id, "status": "staged", "approval_request_id": request_id,
            "note": "Approve at POST /api/approval/{id}/approve to record the decision."}


@router.post("/isolate-host", dependencies=[require_permission("response:manage")])
async def isolate_host(req: IsolateHostRequest, request: Request, user: dict = Depends(get_authenticated_user)):
    """Always staged, never auto-executed — see module docstring."""
    _require()
    try:
        sanitize_target(req.target)
        check_authorization_and_scope(req.target, "isolate_host", user["username"], db=_db)
    except (ValueError, AuthorizationError) as e:
        raise HTTPException(status_code=403, detail=str(e))

    request_id = str(uuid.uuid4())
    pqc_entry = _pqc_sign("isolate_host_staged", {"target": req.target, "reason": req.reason}, user["username"])
    _db.create_approval_request({
        "request_id": request_id, "requested_by": user["username"],
        "action_type": "isolate_host_staged", "target": req.target, "phase": "containment",
        "risk_level": "HIGH", "summary": f"Host isolation requested: {req.reason}",
        "payload_detail": {"target": req.target, "reason": req.reason, "d3fend_technique": "D3-NI"},
        "pqc_entry_id": pqc_entry, "origin_module": "response_router",
    })
    action_id = _record_action("isolate_host_staged", req.target, "staged", "HIGH",
                                user["username"], {"reason": req.reason}, approval_request_id=request_id)
    _audit(request, user, "isolate_host_staged", "success", req.target, {"approval_request_id": request_id})
    return {"action_id": action_id, "status": "staged", "approval_request_id": request_id,
            "d3fend_technique": "D3-NI",
            "note": "Approve at POST /api/approval/{id}/approve to record the decision. "
                    "This platform does not itself control the target's network fabric — "
                    "an approved isolation is the authorization record a real firewall/EDR "
                    "integration or on-call operator acts on."}


# ══════════════════════════════════════════════════════════════════════════
# History / stats
# ══════════════════════════════════════════════════════════════════════════

@router.get("/actions")
async def list_actions(action_type: Optional[str] = None, status: Optional[str] = None, limit: int = 100):
    _require()
    return {"actions": _db.list_remediation_actions(action_type=action_type, status=status,
                                                       limit=max(1, min(limit, 500)))}


@router.get("/stats")
async def stats():
    _require()
    return _db.remediation_stats()
