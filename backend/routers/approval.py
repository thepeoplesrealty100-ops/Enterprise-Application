"""
backend/routers/approval.py
============================
Human Approval Gate API router (JAKAL v2.3).

Backend: security_agents/exploit_agent.py's ExploitAgent, persisted to the
approval_requests table (database.py). Every HIGH/CRITICAL-risk staged
payload — whether staged here directly or auto-staged by
AIPPayloadGenerator.generate() for a high-risk plan — sits as 'pending'
until a human operator calls /approval/{request_id}/approve or /deny.
execute_staged_payload() (called via /approval/{request_id}/execute)
refuses to report success on anything still pending.

Endpoints:
  GET   /approval/status               — gate stats (pending/approved/denied counts)
  GET   /approval/pending              — list pending requests (source of truth: DB)
  POST  /approval/stage                — stage payloads from MITRE ATT&CK mappings
  GET   /approval/audit/recent         — v3.0 Phase 3: recent high-risk decisions with
                                          re-verified PQC signatures + Maya linkage
  GET   /approval/{request_id}         — one request's current status (raw row)
  GET   /approval/{request_id}/context — v3.0 Phase 3: enriched decision context (risk,
                                          blast radius, reversibility, Maya status,
                                          PQC verification result, status timeline) --
                                          see ExploitAgent.get_enriched_approval_context()
  POST  /approval/{request_id}/approve — human approves
  POST  /approval/{request_id}/deny    — human denies
  POST  /approval/{request_id}/execute — run the (simulated) approved payload
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status as http_status
from pydantic import BaseModel

try:
    from security_agents.exploit_agent import ExploitAgent
    from database import DuckDBManager, get_db_manager
    _db: Optional[DuckDBManager] = get_db_manager()
    _gate = ExploitAgent(db_manager=_db)
    APPROVAL_OK = True
except Exception as _e:
    APPROVAL_OK = False
    _APPROVAL_ERR = str(_e)
    _gate = None


class StageRequest(BaseModel):
    attack_mappings: List[Dict[str, Any]]
    target: str = ""
    operator_id: str = "system"


class DecisionRequest(BaseModel):
    operator_id: str
    reason: str = ""


router = APIRouter(prefix="/approval", tags=["human-approval-gate"])


def _require():
    if not APPROVAL_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Approval gate unavailable: {_APPROVAL_ERR}")


@router.get("/status")
def approval_status():
    _require()
    return _gate.gate_status()


@router.get("/pending")
def approval_pending():
    _require()
    pending = _gate.list_pending_approvals()
    return {"count": len(pending), "requests": pending}


@router.post("/stage", status_code=http_status.HTTP_201_CREATED)
def approval_stage(req: StageRequest):
    """Stage payloads for the given MITRE ATT&CK mappings — creates 'pending' rows."""
    _require()
    staged = _gate.stage_payloads(req.attack_mappings, target=req.target, operator_id=req.operator_id)
    return {"staged_count": len(staged), "payloads": staged}


@router.get("/audit/recent")
def approval_audit_recent(risk_level: Optional[str] = None, limit: int = 25):
    """v3.0 Phase 3 audit view: recent decided (approved/denied)
    high-risk (HIGH/CRITICAL) requests, each with its Maya session
    linkage and an actual PQC re-verification result (not just "we have a
    signature on file" -- verify_stored_entry() re-checks it against the
    algorithm/public key recorded at signing time)."""
    _require()
    if not _db:
        raise HTTPException(status_code=503, detail="database unavailable")
    risk_levels = [risk_level] if risk_level else ["HIGH", "CRITICAL"]
    decisions: List[Dict[str, Any]] = []
    for status in ("approved", "denied"):
        for row in _db.list_approval_requests(status=status, limit=limit):
            if row.get("risk_level") in risk_levels:
                decisions.append(row)
    decisions.sort(key=lambda r: r.get("decided_at") or r.get("requested_at"), reverse=True)
    decisions = decisions[:limit]
    return {
        "count": len(decisions),
        "decisions": [_gate.get_enriched_approval_context(r["request_id"]) for r in decisions],
    }


@router.get("/{request_id}")
def approval_get(request_id: str):
    _require()
    if not _db:
        raise HTTPException(status_code=503, detail="database unavailable")
    row = _db.get_approval_request(request_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Approval request '{request_id}' not found")
    return row


@router.get("/{request_id}/context")
def approval_context(request_id: str):
    """v3.0 Phase 3: enriched approval context for one payload -- risk
    level, blast-radius summary, reversibility, linked Maya session
    status + time remaining, re-verified original PQC signature, and the
    staged->challenge_issued->challenge_consumed->approved/denied->
    executed_simulated status timeline. Read-only; makes no decision."""
    _require()
    context = _gate.get_enriched_approval_context(request_id)
    if not context:
        raise HTTPException(status_code=404, detail=f"Approval request '{request_id}' not found")
    return context


def _decision_error_status(message: str) -> int:
    """error, but not "not found" — the payload exists and the request is
    otherwise well-formed, it's just blocked (e.g. the Maya-Vigesimal
    interlock hasn't been consumed yet). 409 Conflict is the honest code
    for "this resource exists but isn't in a state that allows this
    action" -- a 404 here would read as "no such payload," which is
    wrong and would send an operator chasing the wrong problem."""
    return 404 if "not found" in (message or "").lower() else 409


@router.post("/{request_id}/approve")
def approval_approve(request_id: str, req: DecisionRequest):
    _require()
    result = _gate.approve_payload(request_id, req.operator_id, req.reason)
    if result.get("status") == "error":
        raise HTTPException(status_code=_decision_error_status(result.get("message")), detail=result.get("message"))
    return result


@router.post("/{request_id}/deny")
def approval_deny(request_id: str, req: DecisionRequest):
    _require()
    result = _gate.reject_payload(request_id, req.operator_id, req.reason)
    if result.get("status") == "error":
        raise HTTPException(status_code=_decision_error_status(result.get("message")), detail=result.get("message"))
    return result


@router.post("/{request_id}/execute")
def approval_execute(request_id: str):
    """Run the (simulated) payload — refuses unless it has been approved."""
    _require()
    result = _gate.execute_staged_payload(request_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result
