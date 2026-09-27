"""
backend/mcp_server.py — JAKAL's Model Context Protocol (MCP) server.

Exposes real JAKAL platform capabilities as MCP tools for MCP-speaking
clients (Claude Desktop, other external agents) over stdio:

  - get_fleet_status          real device fleet + MSP tenant attribution
                              (GET /api/dashboard/fleet)
  - get_fabric_health         real 7-pillar Zero Trust posture
                              (GET /api/dashboard/fabric/status)
  - execute_remediation_script  queue a real script-catalog entry for
                              execution (POST /scripts/{id}/sandbox-execute),
                              RBAC-gated on response:script_exec

This process is deliberately a THIN HTTP CLIENT of the already-running
JAKAL FastAPI backend (see backend/agents/tools.py) rather than a second
code path that talks to DuckDB directly. That means every tool call gets
the platform's real RBAC, real actor-identity resolution and real audit
trail for free, instead of risking a parallel implementation drifting out
of sync with (or bypassing) the one already tested in
tests/test_energy_logic_and_scripts_security.py.

Run standalone (the JAKAL backend must already be running -- see
config.JAKAL_API_BASE_URL / start.sh):

    python backend/mcp_server.py

Configure an MCP client (e.g. Claude Desktop) to launch this with that same
command; set JAKAL_API_BASE_URL and, for execute_remediation_script,
JAKAL_MCP_BEARER_TOKEN in its env.
"""
import logging
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from agents.schemas import FabricHealthResult, FleetStatusResult, RemediationScriptResult
from agents.tools import execute_remediation_script as _execute_remediation_script
from agents.tools import get_fabric_health as _get_fabric_health
from agents.tools import get_fleet_status as _get_fleet_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("jakal-security-fabric")


def _audit_logger():
    """Lazily built so importing this module never requires a live DB file
    (e.g. under a test collector) -- mirrors routers/scripts.py's own
    best-effort AuditLogger construction."""
    try:
        from core.audit_logger import AuditLogger
        from database import get_db_manager
        return AuditLogger(get_db_manager())
    except Exception as e:  # noqa: BLE001
        logger.warning("MCP audit logging unavailable: %s", e)
        return None


def _audit(tool: str, result: str, details: Optional[Dict[str, Any]] = None) -> None:
    logger_instance = _audit_logger()
    if logger_instance is None:
        return
    try:
        logger_instance.log(
            event_type="mcp_tool_invoked",
            action=tool,
            actor="mcp-client",
            resource=tool,
            result=result,
            details=details or {},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("MCP audit log write failed for %s: %s", tool, e)


@mcp.tool()
async def get_fleet_status(client: Optional[str] = None, page: int = 1,
                            per_page: int = 20) -> Dict[str, Any]:
    """
    Real managed-device fleet with MSP tenant attribution.

    Args:
        client: Optional real tenant id or display name to filter by (see
            available_clients in the response for the real, current list --
            never a hardcoded company name).
        page: 1-based page number.
        per_page: Page size (max 100).
    """
    try:
        result: FleetStatusResult = await _get_fleet_status(client=client, page=page, per_page=per_page)
    except Exception as e:  # noqa: BLE001
        _audit("get_fleet_status", "failure", {"error": str(e)})
        raise
    _audit("get_fleet_status", "success", {"device_count": len(result.data)})
    return result.model_dump()


@mcp.tool()
async def get_fabric_health() -> Dict[str, Any]:
    """Real 7-pillar Unified Security Fabric (Zero Trust) posture and score."""
    try:
        result: FabricHealthResult = await _get_fabric_health()
    except Exception as e:  # noqa: BLE001
        _audit("get_fabric_health", "failure", {"error": str(e)})
        raise
    _audit("get_fabric_health", "success", {"overall_score": result.overall_score})
    return result.model_dump()


@mcp.tool()
async def execute_remediation_script(script_id: str, parameters: Optional[Dict[str, Any]] = None,
                                      timeout_seconds: int = 300) -> Dict[str, Any]:
    """
    Queue a real, catalog-approved remediation script for execution on the
    host (no container isolation -- see routers/scripts.py). RBAC-gated on
    response:script_exec: requires JAKAL_MCP_BEARER_TOKEN to be set to a
    real Bearer token for a service account holding that permission; fails
    honestly (no silent bypass, no fabricated success) if it is not.

    Args:
        script_id: A real script_library.script_id (see GET /scripts/catalog).
        parameters: Script parameters, forwarded verbatim to the execution.
        timeout_seconds: Execution timeout.
    """
    try:
        result: RemediationScriptResult = await _execute_remediation_script(
            script_id=script_id, parameters=parameters, timeout_seconds=timeout_seconds,
        )
    except Exception as e:  # noqa: BLE001
        _audit("execute_remediation_script", "failure", {"script_id": script_id, "error": str(e)})
        raise
    _audit("execute_remediation_script", "success",
           {"script_id": script_id, "execution_id": result.execution_id})
    return result.model_dump()


if __name__ == "__main__":
    mcp.run()
