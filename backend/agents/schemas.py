"""
backend/agents/schemas.py — Pydantic response models for the deep agent loop
and the MCP tool layer (backend/agents/tools.py, backend/mcp_server.py).

These mirror the REAL response shapes of the endpoints they wrap
(routers/ui_bridge.py's GET /dashboard/fleet + GET /dashboard/fabric/status,
routers/scripts.py's POST /{script_id}/sandbox-execute) field-for-field.
They intentionally do NOT invent a `fleet_devices` table shape or an
`audit_logs(action, status)` shape -- there is no such schema in this
platform; see database.py's network_map, agent_logs and resonance_audit_trail
tables instead.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FleetDevice(BaseModel):
    """One row from GET /api/dashboard/fleet — a real network_map device."""
    id: int
    name: str
    ip: Optional[str] = None
    os: Optional[str] = None
    mac: Optional[str] = None
    risk: float = 0.0
    tags: List[str] = Field(default_factory=list)
    discovered: Optional[str] = None
    client_tenant_id: Optional[str] = None
    client: Optional[str] = None


class AvailableClient(BaseModel):
    tenant_id: str
    client_name: str


class FleetStatusResult(BaseModel):
    """Validated shape of GET /api/dashboard/fleet."""
    data: List[FleetDevice] = Field(default_factory=list)
    pagination: Dict[str, Any] = Field(default_factory=dict)
    available_clients: List[AvailableClient] = Field(default_factory=list)


class FabricPillar(BaseModel):
    score: float
    level: str
    capabilities: List[Dict[str, Any]] = Field(default_factory=list)


class FabricHealthResult(BaseModel):
    """Validated shape of GET /api/dashboard/fabric/status."""
    fabric: str
    overall_score: float
    overall_level: str
    capability_count: int
    by_pillar: Dict[str, FabricPillar] = Field(default_factory=dict)
    timestamp: str


class RemediationScriptResult(BaseModel):
    """Validated shape of POST /api/scripts/{script_id}/sandbox-execute.

    Execution is queued and runs in the background on the real backend
    (routers/scripts.py's _execute_script_background) -- this model
    reflects the queued-acceptance response, not a synchronous result.
    Poll GET /api/scripts/executions/{execution_id}/result for outcome.
    """
    execution_id: str
    script_id: str
    status: str
    message: str


class ScriptCatalogEntry(BaseModel):
    """One row from GET /api/scripts/catalog."""
    script_id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    approved: bool = False


class PatchDecision(BaseModel):
    """
    SelfCorrectingAgent output schema for the `autonomous_patch` workflow
    (routers/agent_workflows.py). script_id must name a real, approved entry
    already present in the script catalog the agent was given -- the
    workflow rejects any id that doesn't (see _validate_patch_decision) so
    the model can't invent a script that doesn't exist in this platform.
    """
    script_id: str = Field(..., description="A script_id from the provided catalog, verbatim.")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(..., description="One or two sentences on why this script fits the target.")


class ThreatHuntFinding(BaseModel):
    """
    SelfCorrectingAgent output schema for the `threat_hunter` workflow
    (routers/agent_workflows.py). Read-only synthesis over real fleet +
    fabric data -- this workflow never executes a remediation script.
    """
    summary: str
    risk_level: str = Field(..., description="One of: low, medium, high, critical")
    recommended_action: Optional[str] = None


class AgentWorkflowRunResult(BaseModel):
    """Validated shape of a routers/agent_workflows.py run record."""
    run_id: str
    workflow: str
    operator_id: str
    target: Optional[str] = None
    status: str
    attempts: int = 0
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
