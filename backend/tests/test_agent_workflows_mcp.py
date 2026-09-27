"""
backend/tests/test_agent_workflows_mcp.py

Covers backend/routers/agent_workflows.py -- the FastAPI background-worker
hooks that let the UI or an external MCP client (backend/mcp_server.py)
trigger a self-correcting deep agent loop run (backend/agents/deep_agent_loop.py)
against this platform's own real endpoints -- plus the agent_workflow_runs
DB helpers (database.py) and SelfCorrectingAgent's retry logic in isolation.

services.llm_client is mocked throughout (see test_assistant_generate.py's
docstring for why): this suite must never depend on a real Claude API key or
a running Ollama instance. agents/tools.py's get_fleet_status/get_fabric_health/
get_script_catalog are also monkeypatched for the round-trip tests below --
under ASGITransport there is no live server listening on JAKAL_API_BASE_URL
for those tools' real httpx calls to reach, so the workflows would otherwise
fail on a connection error before ever exercising the logic under test (the
schema-validation retry loop, and -- the actual safety property this suite
exists to prove -- that autonomous_patch refuses a script_id the model
invented outside the real, fetched catalog).

Run: cd backend && python -m pytest tests/test_agent_workflows_mcp.py -q
"""
import asyncio
import sys
import types
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
sys.modules.setdefault("anthropic", types.ModuleType("anthropic"))


@pytest.fixture(scope="module")
def app():
    from app import app as _app
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


_ROOT_USERNAME = _uniq("agentwfroot")
_ROOT_PASSWORD = "Agent-Workflows-Root-Str0ng-Passphrase-2026!"
_READONLY_USERNAME = _uniq("agentwfro")
_READONLY_PASSWORD = "Agent-Workflows-Readonly-Str0ng-Passphrase-2026!"


async def _root_admin_headers(client) -> dict:
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    user = get_db_manager().get_user_by_username(_ROOT_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _read_only_headers(client) -> dict:
    """A real, authenticated user who lacks response:script_exec -- proves
    the 403 (authenticated-but-forbidden) path, distinct from 401 (no token)."""
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _READONLY_USERNAME, "password": _READONLY_PASSWORD})
    user = get_db_manager().get_user_by_username(_READONLY_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "read_only")
    login = await client.post("/api/iam/auth/login", json={"username": _READONLY_USERNAME, "password": _READONLY_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _poll_run(client, run_id, headers):
    status_body = None
    for _ in range(20):
        resp = await client.get(f"/api/agent-workflows/runs/{run_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        status_body = resp.json()
        if status_body["status"] != "queued":
            break
        await asyncio.sleep(0.05)
    return status_body


def _empty_fleet():
    from agents.schemas import FleetStatusResult
    return FleetStatusResult(data=[], pagination={}, available_clients=[])


def _fake_fabric():
    from agents.schemas import FabricHealthResult
    return FabricHealthResult(
        fabric="unified", overall_score=87.5, overall_level="strong",
        capability_count=7, by_pillar={}, timestamp="2026-09-27T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# RBAC gating on POST /api/agent-workflows/trigger
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_requires_auth(client):
    # First registered user in this test module ends bootstrap mode for the
    # shared test DB, so an unauthenticated call must now be rejected.
    await _root_admin_headers(client)

    resp = await client.post("/api/agent-workflows/trigger", json={"workflow": "threat_hunter"})
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_trigger_requires_response_script_exec_permission(client):
    headers = await _read_only_headers(client)
    resp = await client.post("/api/agent-workflows/trigger", json={"workflow": "threat_hunter"}, headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_trigger_unknown_workflow_400s(client):
    headers = await _root_admin_headers(client)
    resp = await client.post("/api/agent-workflows/trigger",
                              json={"workflow": "not_a_real_workflow"}, headers=headers)
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# threat_hunter: real queue -> background run -> poll round trip, LLM mocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_threat_hunter_round_trip_with_mocked_llm(client, monkeypatch):
    headers = await _root_admin_headers(client)

    import agents.deep_agent_loop as deep_agent_loop
    import agents.tools as agent_tools

    async def fake_get_fleet_status(client=None, page=1, per_page=20):
        return _empty_fleet()

    async def fake_get_fabric_health():
        return _fake_fabric()

    monkeypatch.setattr(agent_tools, "get_fleet_status", fake_get_fleet_status)
    monkeypatch.setattr(agent_tools, "get_fabric_health", fake_get_fabric_health)

    def fake_generate(system_prompt, user_prompt, json_schema=None, temperature=0.5, max_tokens=1024):
        return {
            "json": {
                "summary": "No active exploitation observed in the sampled fleet.",
                "risk_level": "low",
                "recommended_action": None,
            },
            "text": "...",
        }
    monkeypatch.setattr(deep_agent_loop, "generate", fake_generate)

    resp = await client.post("/api/agent-workflows/trigger",
                              json={"workflow": "threat_hunter", "target": None}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    run_id = body["run_id"]
    assert body["status"] == "queued"

    status_body = await _poll_run(client, run_id, headers)
    assert status_body["status"] == "completed", status_body
    assert status_body["result"]["risk_level"] == "low"
    assert status_body["operator_id"] == _ROOT_USERNAME


# ---------------------------------------------------------------------------
# autonomous_patch: the agent cannot invent a script_id outside the real
# catalog -- this is the load-bearing safety check, not just schema shape.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_autonomous_patch_rejects_hallucinated_script_id(client, monkeypatch):
    headers = await _root_admin_headers(client)

    import agents.deep_agent_loop as deep_agent_loop
    import agents.tools as agent_tools
    from agents.schemas import ScriptCatalogEntry

    async def fake_get_script_catalog(approved_only=True):
        return [ScriptCatalogEntry(script_id="real-script-1", name="Real Script", approved=True)]

    async def fake_get_fleet_status(client=None, page=1, per_page=20):
        return _empty_fleet()

    monkeypatch.setattr(agent_tools, "get_script_catalog", fake_get_script_catalog)
    monkeypatch.setattr(agent_tools, "get_fleet_status", fake_get_fleet_status)

    def fake_generate(system_prompt, user_prompt, json_schema=None, temperature=0.5, max_tokens=1024):
        return {
            "json": {
                "script_id": "invented-script-does-not-exist",
                "parameters": {},
                "rationale": "This script totally exists, trust me.",
            },
            "text": "...",
        }
    monkeypatch.setattr(deep_agent_loop, "generate", fake_generate)

    resp = await client.post("/api/agent-workflows/trigger",
                              json={"workflow": "autonomous_patch", "target": None}, headers=headers)
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    status_body = await _poll_run(client, run_id, headers)
    assert status_body["status"] == "failed", status_body
    assert "invented-script-does-not-exist" in status_body["error"]
    assert "real-script-1" in status_body["error"]


@pytest.mark.asyncio
async def test_autonomous_patch_empty_catalog_fails_honestly(client, monkeypatch):
    headers = await _root_admin_headers(client)

    import agents.tools as agent_tools

    async def fake_empty_catalog(approved_only=True):
        return []
    monkeypatch.setattr(agent_tools, "get_script_catalog", fake_empty_catalog)

    resp = await client.post("/api/agent-workflows/trigger",
                              json={"workflow": "autonomous_patch", "target": None}, headers=headers)
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    status_body = await _poll_run(client, run_id, headers)
    assert status_body["status"] == "failed", status_body
    assert "No approved scripts" in status_body["error"]


# ---------------------------------------------------------------------------
# GET /runs / GET /runs/{run_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_runs_includes_recent_run(client, monkeypatch):
    headers = await _root_admin_headers(client)

    import agents.tools as agent_tools

    async def fake_empty_catalog(approved_only=True):
        return []
    monkeypatch.setattr(agent_tools, "get_script_catalog", fake_empty_catalog)

    resp = await client.post("/api/agent-workflows/trigger",
                              json={"workflow": "autonomous_patch", "target": None}, headers=headers)
    run_id = resp.json()["run_id"]

    listing = await client.get("/api/agent-workflows/runs", headers=headers)
    assert listing.status_code == 200, listing.text
    run_ids = {r["run_id"] for r in listing.json()["runs"]}
    assert run_id in run_ids


@pytest.mark.asyncio
async def test_get_unknown_run_404s(client):
    headers = await _root_admin_headers(client)
    resp = await client.get("/api/agent-workflows/runs/does-not-exist", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SelfCorrectingAgent: bounded, LLM-driven retry on schema validation failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_self_correcting_agent_retries_then_succeeds(monkeypatch):
    import agents.deep_agent_loop as deep_agent_loop
    from agents.schemas import ThreatHuntFinding

    calls = []

    def fake_generate(system_prompt, user_prompt, json_schema=None, temperature=0.5, max_tokens=1024):
        calls.append(user_prompt)
        if len(calls) == 1:
            # Missing the required risk_level field -- must fail validation.
            return {"json": {"summary": "partial"}, "text": "..."}
        return {"json": {"summary": "ok", "risk_level": "medium", "recommended_action": None}, "text": "..."}

    monkeypatch.setattr(deep_agent_loop, "generate", fake_generate)

    agent = deep_agent_loop.SelfCorrectingAgent(max_retries=3)
    result = await agent.execute_with_validation(
        system_prompt="sys", user_prompt="find threats", validation_schema=ThreatHuntFinding,
    )
    assert result.risk_level == "medium"
    assert len(calls) == 2
    # The retry prompt must include the concrete validation error, not just
    # "try again" -- that's what makes it self-correcting rather than a
    # blind retry.
    assert "risk_level" in calls[1]


@pytest.mark.asyncio
async def test_self_correcting_agent_exhausts_retries_and_raises(monkeypatch):
    import agents.deep_agent_loop as deep_agent_loop
    from agents.schemas import ThreatHuntFinding

    def always_bad(system_prompt, user_prompt, json_schema=None, temperature=0.5, max_tokens=1024):
        return {"json": {"summary": "still wrong"}, "text": "..."}
    monkeypatch.setattr(deep_agent_loop, "generate", always_bad)

    agent = deep_agent_loop.SelfCorrectingAgent(max_retries=2)
    with pytest.raises(deep_agent_loop.AgentValidationError):
        await agent.execute_with_validation(
            system_prompt="sys", user_prompt="find threats", validation_schema=ThreatHuntFinding,
        )


@pytest.mark.asyncio
async def test_self_correcting_agent_propagates_llm_unavailable_without_retrying(monkeypatch):
    """LLMUnavailable is an infrastructure failure, not a content mistake --
    it must propagate immediately rather than burning retries."""
    import agents.deep_agent_loop as deep_agent_loop
    import services.llm_client as llm_client
    from agents.schemas import ThreatHuntFinding

    calls = []

    def raise_unavailable(system_prompt, user_prompt, json_schema=None, temperature=0.5, max_tokens=1024):
        calls.append(1)
        raise llm_client.LLMUnavailable("no backend configured in test env")
    monkeypatch.setattr(deep_agent_loop, "generate", raise_unavailable)

    agent = deep_agent_loop.SelfCorrectingAgent(max_retries=3)
    with pytest.raises(llm_client.LLMUnavailable):
        await agent.execute_with_validation(
            system_prompt="sys", user_prompt="find threats", validation_schema=ThreatHuntFinding,
        )
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# agents/tools.py: execute_remediation_script requires a real service-account
# bearer token -- never a silently-skipped auth check.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_remediation_script_requires_mcp_bearer_token(monkeypatch):
    from agents.tools import execute_remediation_script, ToolAuthError
    from config import get_config

    # No JAKAL_MCP_BEARER_TOKEN is set in this test environment (the
    # established CI invocation only sets DUCKDB_PATH + JAKAL_MASTER_KEY) --
    # confirm that honestly, rather than assuming, before relying on it.
    assert not get_config().JAKAL_MCP_BEARER_TOKEN

    with pytest.raises(ToolAuthError):
        await execute_remediation_script(script_id="whatever", parameters={})
