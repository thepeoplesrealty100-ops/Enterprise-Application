"""
backend/agents/tools.py — real tool bindings for the deep agent loop and the
MCP server (backend/mcp_server.py).

Design: each tool is an HTTP client of THIS backend's own already-existing
routers, not a second copy of their DB/business logic. That means every tool
call gets the real RBAC gate, the real actor-identity resolution (Bearer JWT
-> username, never a caller-supplied id) and the real audit trail that those
routers already have and are already tested against
(tests/test_energy_logic_and_scripts_security.py) -- an agent/MCP caller
can't get a shortcut a human operator doesn't also have.

get_fleet_status / get_fabric_health call public routers/ui_bridge.py
endpoints (no auth dependency on that router at all -- verified by grep).
execute_remediation_script calls the RBAC-gated (response:script_exec)
POST /scripts/{id}/sandbox-execute and therefore needs a real Bearer token;
see config.JAKAL_MCP_BEARER_TOKEN. No token configured -> ToolAuthError,
never a silently-skipped auth check.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from agents.schemas import (
    FabricHealthResult,
    FleetStatusResult,
    RemediationScriptResult,
    ScriptCatalogEntry,
)

logger = logging.getLogger(__name__)


class ToolCallError(RuntimeError):
    """The backend rejected or failed a tool's HTTP call. Never swallowed."""


class ToolAuthError(ToolCallError):
    """A permission-gated tool was called with no service-account token."""


def _get_config():
    from config import get_config
    return get_config()


def _base_url() -> str:
    return _get_config().JAKAL_API_BASE_URL.rstrip("/")


async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params or {})
    except httpx.HTTPError as e:
        raise ToolCallError(f"GET {path} unreachable: {e}") from e
    if resp.status_code != 200:
        raise ToolCallError(f"GET {path} returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def _post_authenticated(path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
    token = _get_config().JAKAL_MCP_BEARER_TOKEN
    if not token:
        raise ToolAuthError(
            "JAKAL_MCP_BEARER_TOKEN is not configured. Obtain one for a service "
            "account holding the response:script_exec permission via "
            "POST /api/iam/auth/login, then set JAKAL_MCP_BEARER_TOKEN -- this "
            "tool will not call a permission-gated endpoint without it."
        )
    url = f"{_base_url()}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=json_body, headers=headers)
    except httpx.HTTPError as e:
        raise ToolCallError(f"POST {path} unreachable: {e}") from e
    if resp.status_code == 401:
        raise ToolAuthError(f"POST {path}: JAKAL_MCP_BEARER_TOKEN was rejected (401) -- token expired or invalid.")
    if resp.status_code == 403:
        raise ToolAuthError(f"POST {path}: service account lacks the required permission (403).")
    if resp.status_code not in (200, 201):
        raise ToolCallError(f"POST {path} returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def get_fleet_status(client: Optional[str] = None, page: int = 1,
                            per_page: int = 20) -> FleetStatusResult:
    """Real device fleet + tenant attribution, via GET /api/dashboard/fleet."""
    params: Dict[str, Any] = {"page": page, "per_page": per_page}
    if client:
        params["client"] = client
    data = await _get("/api/dashboard/fleet", params)
    return FleetStatusResult.model_validate(data)


async def get_fabric_health() -> FabricHealthResult:
    """Real 7-pillar Zero Trust posture, via GET /api/dashboard/fabric/status."""
    data = await _get("/api/dashboard/fabric/status")
    return FabricHealthResult.model_validate(data)


async def get_script_catalog(approved_only: bool = True) -> list[ScriptCatalogEntry]:
    """Real, catalog-approved scripts, via GET /api/scripts/catalog."""
    data = await _get("/api/scripts/catalog", {"approved_only": approved_only, "limit": 100})
    return [ScriptCatalogEntry.model_validate(row) for row in data.get("scripts", [])]


async def execute_remediation_script(script_id: str, parameters: Optional[Dict[str, Any]] = None,
                                      timeout_seconds: int = 300) -> RemediationScriptResult:
    """
    Queue a real script-catalog entry for execution, via the RBAC-gated
    POST /api/scripts/{script_id}/sandbox-execute. `operator_id` in the
    request body is accepted by that endpoint's schema but ignored server
    side in favor of the real Bearer-token identity -- see scripts.py's
    _actor(); it is sent here only because ScriptExecutionRequest requires
    the field.
    """
    body = {
        "script_id": script_id,
        "operator_id": "mcp-agent",
        "parameters": parameters or {},
        "timeout_seconds": timeout_seconds,
    }
    data = await _post_authenticated(f"/api/scripts/{script_id}/sandbox-execute", body)
    return RemediationScriptResult.model_validate(data)
