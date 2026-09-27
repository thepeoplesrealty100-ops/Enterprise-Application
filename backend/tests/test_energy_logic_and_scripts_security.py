"""
backend/tests/test_energy_logic_and_scripts_security.py

Covers two unrelated fixes made in the same pass:

1. routers/energy_logic.py's POST /api/energy-logic/logic-execute used to
   queue a background task that silently discarded its results (`except
   Exception: pass  # Log error`) with no way to check on it afterwards.
   It's now backed by a real `energy_logic_executions` table
   (database.py) and a new GET /logic-execute/{execution_id} status
   endpoint. These tests exercise the real round trip -- queue, poll,
   confirm real per-operation timing and persisted results -- and confirm
   an unknown operation type is rejected and persisted as "failed" with a
   real error message, rather than being silently marked "completed".

2. routers/scripts.py had *zero* authentication or RBAC anywhere in the
   file (confirmed by grep: no require_permission/get_authenticated_user/
   Depends in the whole module) despite POST /{script_id}/sandbox-execute
   performing real, unsandboxed `subprocess.run` execution on the host.
   Catalog mutations (create/approve) also trusted a free-text
   `operator_id`/`approval_by` query param as the actor, so any anonymous
   caller could attribute an upload or approval to "admin". These tests
   confirm the three mutating endpoints (create, approve, sandbox-execute)
   now require a real Bearer token + response:manage/response:script_exec,
   and that the persisted actor is the authenticated identity rather than
   client-supplied text.

Run: cd backend && python -m pytest tests/test_energy_logic_and_scripts_security.py -q
"""
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


_ROOT_USERNAME = _uniq("scriptsroot")
_ROOT_PASSWORD = "Scripts-Root-Str0ng-Passphrase-2026!"


async def _root_admin_headers(client) -> dict:
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    user = get_db_manager().get_user_by_username(_ROOT_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ---------------------------------------------------------------------------
# energy_logic.py: real execute -> status round trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logic_execute_persists_real_results(client):
    chain = {
        "chain_id": _uniq("chain"),
        "operations": [
            {"type": "threat_assessment"},
            {"type": "resource_optimization"},
        ],
        "execution_order": "sequential",
    }
    queued = await client.post("/api/energy-logic/logic-execute", json=chain)
    assert queued.status_code == 200, queued.text
    body = queued.json()
    execution_id = body["execution_id"]
    assert body["status"] == "queued"
    assert body["status_url"] == f"/api/energy-logic/logic-execute/{execution_id}"

    # Background task runs inline-ish under ASGITransport but may need a beat;
    # poll a bounded number of times rather than sleeping blindly.
    import asyncio
    status_body = None
    for _ in range(20):
        resp = await client.get(f"/api/energy-logic/logic-execute/{execution_id}")
        assert resp.status_code == 200, resp.text
        status_body = resp.json()
        if status_body["status"] != "queued":
            break
        await asyncio.sleep(0.05)

    assert status_body["status"] == "completed", status_body
    assert status_body["chain_id"] == chain["chain_id"]
    assert status_body["error"] is None
    assert len(status_body["results"]) == 2
    assert {r["operation_type"] for r in status_body["results"]} == {
        "threat_assessment", "resource_optimization",
    }
    assert status_body["elapsed_ms"] is not None and status_body["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_logic_execute_unknown_operation_type_fails_honestly(client):
    chain = {
        "chain_id": _uniq("chain"),
        "operations": [{"type": "not_a_real_operation"}],
    }
    queued = await client.post("/api/energy-logic/logic-execute", json=chain)
    assert queued.status_code == 200, queued.text
    execution_id = queued.json()["execution_id"]

    import asyncio
    status_body = None
    for _ in range(20):
        resp = await client.get(f"/api/energy-logic/logic-execute/{execution_id}")
        status_body = resp.json()
        if status_body["status"] != "queued":
            break
        await asyncio.sleep(0.05)

    assert status_body["status"] == "failed", status_body
    assert "not_a_real_operation" in status_body["error"]


@pytest.mark.asyncio
async def test_logic_execute_unknown_id_404s(client):
    resp = await client.get("/api/energy-logic/logic-execute/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# scripts.py: RBAC gating on mutating endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_script_requires_auth(client):
    # First registered user in this test module ends bootstrap mode for the
    # shared test DB, so an unauthenticated call must now be rejected --
    # this is exactly the gap this fix closes (previously: 201 Created).
    await _root_admin_headers(client)

    payload = {
        "name": "unauthenticated-upload-attempt",
        "category": "network_recon",
        "language": "bash",
        "script_content": "echo hi",
    }
    resp = await client.post("/api/scripts/catalog", json=payload)
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_create_and_approve_script_with_real_admin_persists_real_actor(client):
    headers = await _root_admin_headers(client)

    payload = {
        "name": _uniq("real-script"),
        "category": "network_recon",
        "language": "bash",
        "script_content": "echo hello",
    }
    created = await client.post("/api/scripts/catalog", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    script_id = created.json()["script_id"]

    detail = await client.get(f"/api/scripts/catalog/{script_id}")
    assert detail.status_code == 200
    # author defaults to the real authenticated actor, never a client-chosen string
    assert detail.json()["author"] == _ROOT_USERNAME
    assert detail.json()["approved"] is False

    approved = await client.post(f"/api/scripts/catalog/{script_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text

    detail2 = await client.get(f"/api/scripts/catalog/{script_id}")
    assert detail2.json()["approved"] is True
    assert detail2.json()["approval_by"] == _ROOT_USERNAME


@pytest.mark.asyncio
async def test_approve_script_requires_permission_not_free_text(client):
    resp = await client.post("/api/scripts/catalog/some-script-id/approve",
                              params={"approval_by": "admin"})
    # No Authorization header at all -- must not be honored as "admin".
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_sandbox_execute_requires_auth_and_permission(client):
    headers = await _root_admin_headers(client)
    payload = {
        "name": _uniq("exec-script"),
        "category": "network_recon",
        "language": "bash",
        "script_content": "echo hi",
    }
    created = await client.post("/api/scripts/catalog", json=payload, headers=headers)
    script_id = created.json()["script_id"]

    unauth = await client.post(
        f"/api/scripts/{script_id}/sandbox-execute",
        json={"script_id": script_id, "operator_id": "anyone"},
    )
    assert unauth.status_code in (401, 403), unauth.text

    authed = await client.post(
        f"/api/scripts/{script_id}/sandbox-execute",
        json={"script_id": script_id, "operator_id": "someone-else-entirely"},
        headers=headers,
    )
    assert authed.status_code == 201, authed.text
    execution_id = authed.json()["execution_id"]

    result = await client.get(f"/api/scripts/executions/{execution_id}/result")
    assert result.status_code == 200
    # The persisted operator_id is the real authenticated actor, not the
    # client-supplied "someone-else-entirely" impersonation attempt.
    assert result.json()["operator_id"] == _ROOT_USERNAME
