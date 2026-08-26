"""
backend/routers/canvas.py
============================
Agentic Canvas API router (JAKAL v2.4) — deployable patch tasks.

Deliberately reuses the v2.3 Human Approval Gate (security_agents/exploit_agent.py
+ the approval_requests table) rather than inventing a second, parallel
authorization mechanism: POST /canvas/deploy-patch stages the patch as both
an agentic_remediation_tasks row AND an approval_requests row, and
deployment_progress cannot move past 0 until that same approval_requests
row is approved — enforced in database.py's advance_remediation_task(),
the same "check the persisted decision, not a flag" pattern used by
ExploitAgent.execute_staged_payload().

Endpoints:
  GET   /canvas/tasks             — list remediation tasks
  GET   /canvas/tasks/{task_id}   — one task's current state
  POST  /canvas/deploy-patch      — stage a patch (creates a pending approval)
  POST  /canvas/tasks/{task_id}/advance — move progress forward (blocked until approved)
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel

try:
    from database import DuckDBManager
    from security_agents.exploit_agent import ExploitAgent
    _db: Optional[DuckDBManager] = DuckDBManager()
    _gate = ExploitAgent(db_manager=_db)
    CANVAS_OK = True
except Exception as _e:
    CANVAS_OK = False
    _CANVAS_ERR = str(_e)
    _db = None
    _gate = None


class DeployPatchRequest(BaseModel):
    target_machine_ip: str
    patch_id: str
    autonomous_action_taken: str = "staged — awaiting operator approval"
    requested_by: str = "system"
    risk_level: str = "HIGH"


class AdvanceRequest(BaseModel):
    progress: int
    status: Optional[str] = None


router = APIRouter(prefix="/canvas", tags=["agentic-canvas"])


def _require():
    if not CANVAS_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Agentic Canvas unavailable: {_CANVAS_ERR}")


@router.get("/tasks")
def list_tasks(status: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500)):
    _require()
    tasks = _db.list_remediation_tasks(status=status, limit=limit)
    return {"count": len(tasks), "tasks": tasks}


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    _require()
    task = _db.sync_remediation_task_approval(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return task


@router.post("/deploy-patch", status_code=http_status.HTTP_201_CREATED)
def deploy_patch(req: DeployPatchRequest):
    """
    Stage a patch deployment. Requires operator authorization before
    execution — implemented by auto-creating a pending approval_requests
    row via the same Human Approval Gate every other high-risk action uses.
    """
    _require()
    task_id = str(uuid.uuid4())

    approval_request_id = str(uuid.uuid4())
    _db.create_approval_request({
        "request_id": approval_request_id,
        "requested_by": req.requested_by,
        "action_type": "agentic_canvas_patch_deploy",
        "target": req.target_machine_ip,
        "phase": "remediation",
        "risk_level": req.risk_level,
        "summary": f"Deploy patch {req.patch_id} to {req.target_machine_ip}",
        "payload_detail": {"patch_id": req.patch_id, "action": req.autonomous_action_taken},
    })

    _db.create_remediation_task({
        "task_id": task_id,
        "target_machine_ip": req.target_machine_ip,
        "patch_id": req.patch_id,
        "autonomous_action_taken": req.autonomous_action_taken,
        "approval_request_id": approval_request_id,
    })

    return {
        "task_id": task_id,
        "approval_request_id": approval_request_id,
        "status": "queued",
        "note": "Approve via POST /api/approval/{approval_request_id}/approve before progress can advance.",
    }


@router.post("/tasks/{task_id}/advance")
def advance_task(task_id: str, req: AdvanceRequest):
    _require()
    result = _db.advance_remediation_task(task_id, req.progress, req.status)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result
