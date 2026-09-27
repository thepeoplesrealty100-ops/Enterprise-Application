"""
backend/routers/agent_workflows.py
===================================
FastAPI background-worker hooks for the self-correcting deep agent loop
(backend/agents/deep_agent_loop.py) — lets the frontend UI or an external
MCP client (backend/mcp_server.py) trigger an autonomous workflow run
against this platform's own real endpoints, with a full DuckDB audit trail.

Two real workflows, each a bounded, schema-validated LLM decision over real
platform data (never a fabricated fleet_devices/audit_logs table):

  - autonomous_patch: given a target (tenant id/name or device), the agent
    picks one script_id from the REAL, approved script catalog and queues it
    for execution via the RBAC-gated sandbox-execute endpoint. The chosen
    script_id is validated against the fetched catalog before it is ever
    executed — the model cannot invent a script that doesn't exist here.
  - threat_hunter: read-only synthesis over real fleet + fabric status into
    a structured finding. Never executes anything.

RBAC-gated on response:script_exec (same permission the underlying
sandbox-execute endpoint requires) since autonomous_patch can end up
executing a remediation script; threat_hunter is gated identically for a
single, predictable permission model rather than two.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-workflows", tags=["agent-workflows"])

WORKFLOWS = ("autonomous_patch", "threat_hunter")


class WorkflowTriggerRequest(BaseModel):
    workflow: str
    target: Optional[str] = None
    parameters: Dict[str, Any] = {}


def _actor(user: dict) -> str:
    """Real caller identity from the verified Bearer token — same rule
    scripts.py's _actor() enforces; never a client-supplied id."""
    return user.get("username") or user.get("user_id") or "system"


async def _run_autonomous_patch(run_id: str, target: Optional[str], parameters: Dict[str, Any]) -> None:
    from agents.deep_agent_loop import AgentValidationError, SelfCorrectingAgent
    from agents.schemas import PatchDecision
    from agents.tools import execute_remediation_script, get_fleet_status, get_script_catalog, ToolCallError
    from database import get_db_manager

    db = get_db_manager()
    try:
        catalog = await get_script_catalog(approved_only=True)
        if not catalog:
            raise ToolCallError("No approved scripts in the catalog — nothing this workflow can run.")
        fleet = await get_fleet_status(client=target)

        catalog_summary = "\n".join(f"- {s.script_id}: {s.name} ({s.category})" for s in catalog)
        device_summary = "\n".join(
            f"- {d.name} ({d.ip}) risk={d.risk} tags={d.tags}" for d in fleet.data[:20]
        ) or "(no devices matched this target)"

        agent = SelfCorrectingAgent(max_retries=3)
        decision: PatchDecision = await agent.execute_with_validation(
            system_prompt=(
                "You are JAKAL's autonomous patch-selection agent. Pick exactly one script_id "
                "from the provided catalog that best remediates the target's real risk profile. "
                "Respond with JSON only, matching the schema."
            ),
            user_prompt=(
                f"Target: {target or '(no filter — whole fleet)'}\n\n"
                f"Approved script catalog:\n{catalog_summary}\n\n"
                f"Devices (up to 20 shown):\n{device_summary}\n\n"
                f"Operator-supplied parameters: {parameters}"
            ),
            validation_schema=PatchDecision,
        )

        valid_ids = {s.script_id for s in catalog}
        if decision.script_id not in valid_ids:
            raise AgentValidationError(
                f"Agent chose script_id={decision.script_id!r}, which is not in the real "
                f"approved catalog ({sorted(valid_ids)}) — refusing to execute."
            )

        exec_result = await execute_remediation_script(
            script_id=decision.script_id, parameters=decision.parameters,
        )
        db.update_agent_workflow_run(
            run_id, status="completed", attempts=1,
            result={"decision": decision.model_dump(), "execution": exec_result.model_dump()},
        )
    except Exception as e:  # noqa: BLE001
        logger.error("autonomous_patch run %s failed: %s", run_id, e)
        db.update_agent_workflow_run(run_id, status="failed", attempts=1, error=str(e))


async def _run_threat_hunter(run_id: str, target: Optional[str], parameters: Dict[str, Any]) -> None:
    from agents.deep_agent_loop import SelfCorrectingAgent
    from agents.schemas import ThreatHuntFinding
    from agents.tools import get_fabric_health, get_fleet_status
    from database import get_db_manager

    db = get_db_manager()
    try:
        fleet = await get_fleet_status(client=target)
        fabric = await get_fabric_health()

        device_summary = "\n".join(
            f"- {d.name} ({d.ip}) risk={d.risk} tags={d.tags}" for d in fleet.data[:30]
        ) or "(no devices matched this target)"

        agent = SelfCorrectingAgent(max_retries=3)
        finding: ThreatHuntFinding = await agent.execute_with_validation(
            system_prompt=(
                "You are JAKAL's threat-hunting analyst agent. Synthesize the real fleet and "
                "fabric posture data given into one structured finding. Respond with JSON only, "
                "matching the schema. This is read-only analysis — you cannot execute anything."
            ),
            user_prompt=(
                f"Target: {target or '(no filter — whole fleet)'}\n\n"
                f"Devices (up to 30 shown):\n{device_summary}\n\n"
                f"Fabric posture: overall_score={fabric.overall_score} "
                f"overall_level={fabric.overall_level}\n\n"
                f"Operator-supplied parameters: {parameters}"
            ),
            validation_schema=ThreatHuntFinding,
        )
        db.update_agent_workflow_run(run_id, status="completed", attempts=1, result=finding.model_dump())
    except Exception as e:  # noqa: BLE001
        logger.error("threat_hunter run %s failed: %s", run_id, e)
        db.update_agent_workflow_run(run_id, status="failed", attempts=1, error=str(e))


_RUNNERS = {
    "autonomous_patch": _run_autonomous_patch,
    "threat_hunter": _run_threat_hunter,
}


@router.post("/trigger", dependencies=[require_permission("response:script_exec")])
async def trigger_workflow(
    req: WorkflowTriggerRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_authenticated_user),
):
    """
    Queue a self-correcting agent workflow run. Returns immediately with a
    run_id; poll GET /api/agent-workflows/runs/{run_id} for the outcome.
    """
    if req.workflow not in WORKFLOWS:
        raise HTTPException(status_code=400, detail=f"Unknown workflow {req.workflow!r}; must be one of {WORKFLOWS}")

    from core.audit_logger import AuditLogger
    from database import get_db_manager

    db = get_db_manager()
    actor = _actor(user)
    run_id = str(uuid.uuid4())
    db.create_agent_workflow_run(run_id, req.workflow, actor, req.target, req.parameters)

    try:
        AuditLogger(db).log(
            event_type="agent_workflow_triggered",
            action=req.workflow,
            actor=actor,
            resource=req.target or "fleet",
            details={"run_id": run_id, "parameters": req.parameters},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Audit log write failed for workflow trigger %s: %s", run_id, e)

    background_tasks.add_task(_RUNNERS[req.workflow], run_id, req.target, req.parameters)
    return {"run_id": run_id, "workflow": req.workflow, "status": "queued"}


@router.get("/runs/{run_id}")
async def get_workflow_run(run_id: str, user: dict = Depends(get_authenticated_user)):
    """Poll a triggered workflow run's status/result."""
    from database import get_db_manager

    db = get_db_manager()
    run = db.get_agent_workflow_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@router.get("/runs")
async def list_workflow_runs(limit: int = 50, user: dict = Depends(get_authenticated_user)):
    """List recent workflow runs (most recent first)."""
    from database import get_db_manager

    db = get_db_manager()
    return {"runs": db.list_agent_workflow_runs(limit=limit)}
