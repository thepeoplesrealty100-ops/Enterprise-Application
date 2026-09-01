"""
backend/routers/cheatsheet.py
===============================
CheatSheet Library API — JAKAL v2.6.

The `admin_cheatsheet_library` frontend page had no live data source even
though the real content already existed server-side: 13 report modules +
43 tool cheat sheets (backend/gacyber_toolkit/CheatSheets/), queried
through the ontology layer in backend/payloads/cheatsheet_ontology.py, and
the response-procedure library in backend/payloads/playbook_library.py.
This router just exposes both as a browsable/searchable read API — no new
data model needed, it reuses the same CheatsheetOntology instance the AIP
payload generator (routers/aip.py) already drives.

Endpoints:
  GET /cheatsheet/stats             — corpus size, category counts
  GET /cheatsheet/categories        — list categories
  GET /cheatsheet/search            — resolve entries by phase/category/keyword
  GET /cheatsheet/entries/{entry_id} — full entry content
  GET /cheatsheet/graph             — ontology graph (objects + links)
  GET /cheatsheet/playbooks         — the response-procedure playbook library
  GET /cheatsheet/playbooks/{key}   — one playbook, full detail

  v2.7 — real, runnable scripts (payloads/script_catalog.py indexes the
  actual .py/.sh/.pl/.rb files under gacyber_toolkit/'s phase folders):
  GET  /cheatsheet/scripts/stats           — corpus size by phase/risk
  GET  /cheatsheet/scripts                 — list (filter by phase/risk/language)
  GET  /cheatsheet/scripts/{id}            — full source, read-only
  POST /cheatsheet/scripts/{id}/stage      — stage for execution behind the
                                              authorization + Human Approval Gate
                                              (never auto-executes — see module note)
  POST /cheatsheet/scripts/{id}/run-in-sandbox — once approved, run ONLY inside
                                              an operator-owned VM Orchestrator
                                              sandbox container (never the host,
                                              never directly against a live target)
"""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

try:
    from payloads.cheatsheet_ontology import CheatsheetOntology
    _ontology = CheatsheetOntology()
    from payloads.playbook_library import PLAYBOOKS
    from payloads.script_catalog import ScriptCatalog
    _scripts = ScriptCatalog()
    from database import get_db_manager
    from tools.authorization import check_authorization_and_scope, AuthorizationError
    from wrappers.base import sanitize_target
    from security_agents.vm_orchestrator import get_vm_orchestrator
    _db = get_db_manager()
    _vm = get_vm_orchestrator(_db)
    CHEATSHEET_OK = True
    _ERR = None
except Exception as _e:  # noqa: BLE001
    CHEATSHEET_OK = False
    _ERR = str(_e)
    _ontology = None
    _scripts = None
    _db = None
    _vm = None
    PLAYBOOKS = {}

from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cheatsheet", tags=["cheatsheet"])


def _require():
    if not CHEATSHEET_OK:
        raise HTTPException(status_code=503, detail=f"CheatSheet library unavailable: {_ERR}")


@router.get("/stats")
async def stats():
    _require()
    return _ontology.stats()


@router.get("/categories")
async def categories():
    _require()
    return {"categories": _ontology.categories()}


@router.get("/search")
async def search(
    phase: Optional[str] = None,
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    include_non_executable: bool = Query(default=True, description="Include reference-only entries (e.g. social engineering docs)"),
    limit: int = Query(default=20, ge=1, le=200),
):
    _require()
    results = _ontology.resolve(
        phase=phase, category=category, keyword=keyword,
        include_non_executable=include_non_executable, limit=limit,
    )
    return {"count": len(results), "entries": results}


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: str):
    _require()
    entry = _ontology.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Cheatsheet entry not found")
    return entry


@router.get("/graph")
async def graph():
    _require()
    return _ontology.ontology_graph()


@router.get("/playbooks")
async def list_playbooks(category: Optional[str] = None):
    if category:
        return {"playbooks": [
            {"key": k, "name": p["name"], "category": p["category"], "phase": p.get("phase"),
             "estimated_hours": p.get("estimated_hours")}
            for k, p in PLAYBOOKS.items() if p.get("category") == category
        ]}
    return {"playbooks": [
        {"key": k, "name": p["name"], "category": p["category"], "phase": p.get("phase"),
         "estimated_hours": p.get("estimated_hours")}
        for k, p in PLAYBOOKS.items()
    ]}


@router.get("/playbooks/{key}")
async def get_playbook(key: str):
    playbook = PLAYBOOKS.get(key)
    if not playbook:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return playbook


# ══════════════════════════════════════════════════════════════════════════
# v2.7 — Script catalog (real, runnable gacyber_toolkit scripts)
# ══════════════════════════════════════════════════════════════════════════

class ScriptStageRequest(BaseModel):
    target: str = Field(..., max_length=256)
    operator_id: str = Field(default="system")


class ScriptRunRequest(BaseModel):
    approval_request_id: str
    container_name: str = Field(..., max_length=128)
    operator_id: str = Field(default="system")


@router.get("/scripts/stats")
async def script_stats():
    _require()
    return _scripts.stats()


@router.get("/scripts")
async def list_scripts(phase: Optional[str] = None, risk_level: Optional[str] = None,
                        language: Optional[str] = None):
    _require()
    return {"scripts": _scripts.list_scripts(phase=phase, risk_level=risk_level, language=language)}


@router.get("/scripts/{script_id}")
async def get_script(script_id: str):
    _require()
    script = _scripts.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return script


@router.post("/scripts/{script_id}/stage", dependencies=[require_permission("response:script_exec")])
async def stage_script(script_id: str, req: ScriptStageRequest, request: Request,
                        user: dict = Depends(get_authenticated_user)):
    """
    Stages a real gacyber_toolkit script for execution. Never runs it
    directly — mirrors security_agents/exploit_agent.py's staging pattern
    exactly: creates an approval_requests row, requires an explicit
    POST /api/approval/{id}/approve, and even then the only execution path
    is POST /cheatsheet/scripts/{id}/run-in-sandbox, which runs inside an
    operator-owned VM Orchestrator container, never the host, never
    directly against the live target.
    """
    _require()
    script = _scripts.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    try:
        sanitize_target(req.target)
        check_authorization_and_scope(req.target, "script_catalog_execution", req.operator_id, db=_db)
    except (ValueError, AuthorizationError) as e:
        raise HTTPException(status_code=403, detail=str(e))

    request_id = str(uuid.uuid4())
    try:
        from crypto.pqc_manager import PQCAuditManager
        pqc = PQCAuditManager()
        signed = pqc.sign_agent_action(
            agent_id="cheatsheet-script-catalog",
            action_payload={"script_id": script_id, "target": req.target},
            operator_id=req.operator_id,
        )
        pqc_entry_id = signed["entry_id"]
    except Exception as e:
        logger.warning("PQC signing unavailable for script staging: %s", e)
        pqc_entry_id = None

    _db.create_approval_request({
        "request_id": request_id, "requested_by": req.operator_id,
        "action_type": "script_catalog_execution", "target": req.target,
        "phase": script["phase"], "risk_level": script["risk_level"],
        "summary": f"Run '{script['title']}' ({script['language']}) against {req.target}",
        "payload_detail": {
            "script_id": script_id, "relative_path": script["relative_path"],
            "content_sha256": script["content_sha256"], "target": req.target,
        },
        "pqc_entry_id": pqc_entry_id, "origin_module": "script_catalog",
    })

    # v2.8: real enforcement of the Resonance Wave Automation policy knob
    # auto_approve_low_risk_actions -- LOW-risk scripts only, and this is
    # the ONLY thing it changes: the human-decision step is skipped, not
    # the authorization gate above (still enforced) or the sandbox-only
    # execution boundary (run-in-sandbox still requires status='approved'
    # and a matching content hash either way).
    auto_approved = False
    if script["risk_level"] == "LOW" and _db.get_policy_value("auto_approve_low_risk_actions", False):
        _db.decide_approval_request(
            request_id, "approved", "system:auto-approve-policy",
            "auto-approved per resonance_policy.auto_approve_low_risk_actions",
        )
        auto_approved = True

    _db.insert_remediation_action({
        "action_id": request_id, "action_type": "script_catalog_execution", "target": req.target,
        "status": "approved" if auto_approved else "staged", "risk_level": script["risk_level"],
        "approval_request_id": request_id,
        "operator_id": req.operator_id, "d3fend_technique": None,
        "detail": {"script_id": script_id, "title": script["title"], "auto_approved": auto_approved},
    })
    return {
        "approval_request_id": request_id,
        "status": "approved" if auto_approved else "staged",
        "risk_level": script["risk_level"],
        "note": (
            "Auto-approved per the auto_approve_low_risk_actions policy — go straight to POST "
            "/cheatsheet/scripts/{script_id}/run-in-sandbox with this approval_request_id."
        ) if auto_approved else (
            "Approve at POST /api/approval/{id}/approve, then POST "
            "/cheatsheet/scripts/{script_id}/run-in-sandbox with the approval_request_id "
            "and a sandbox container_name (create one at POST /api/vm/sandboxes first)."
        ),
    }


@router.post("/scripts/{script_id}/run-in-sandbox", dependencies=[require_permission("vm:exec")])
async def run_script_in_sandbox(script_id: str, req: ScriptRunRequest, request: Request,
                                 user: dict = Depends(get_authenticated_user)):
    """
    Executes an APPROVED staged script inside a sandbox container the
    operator already owns (VMOrchestrator.exec_in_sandbox — the only real
    subprocess-execution path in this whole platform, already isolated to
    an unprivileged, network-bridged, jakal-labeled container). The script
    content is base64-transported into the container to avoid any shell
    quoting/injection surface, written to a temp file, then run with its
    interpreter.
    """
    _require()
    script = _scripts.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")

    approval = _db.get_approval_request(req.approval_request_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.get("status") != "approved":
        raise HTTPException(status_code=403, detail=f"Approval request is '{approval.get('status')}', not 'approved'")
    detail = approval.get("payload_detail") or {}
    if detail.get("script_id") != script_id:
        raise HTTPException(status_code=409, detail="Approval request does not match this script_id")
    if detail.get("content_sha256") != script["content_sha256"]:
        raise HTTPException(status_code=409, detail="Script content has changed since staging — re-stage before running")

    interpreter = {"python": "python3", "bash": "bash", "perl": "perl", "ruby": "ruby"}[script["language"]]
    ext = {"python": "py", "bash": "sh", "perl": "pl", "ruby": "rb"}[script["language"]]
    b64 = base64.b64encode(script["content"].encode("utf-8")).decode("ascii")
    remote_path = f"/tmp/jakal_script_{script_id}.{ext}"
    command = f"bash -lc \"echo {b64} | base64 -d > {remote_path} && {interpreter} {remote_path}\""

    result = _vm.exec_in_sandbox(req.container_name, command, req.operator_id)
    status = "executed_in_sandbox" if result.get("status") == "completed" else "error"
    _db.update_remediation_action_status(req.approval_request_id, status)
    return {"approval_request_id": req.approval_request_id, "script_id": script_id, **result}
