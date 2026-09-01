"""
backend/tests/test_scripts_sandbox_hardening.py
JAKAL — routers/scripts.py sandbox-execute hardening.

Prior to this test file, routers/scripts.py had zero coverage and its
/scripts/{id}/sandbox-execute endpoint ran uploaded script content directly
on the API's own host via subprocess.run, with no permission dependency and
no check that the script had been approved. This suite covers the fix:
execution now requires vm:exec + a valid session, an approved script, and
routes through VMOrchestrator.exec_in_sandbox (a container the operator
owns) instead of a host subprocess.

Run: cd backend && python -m pytest tests/test_scripts_sandbox_hardening.py -q
"""

import sys
import types
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

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


async def _upload_script(client, headers) -> str:
    script_id = _uniq("test-script")
    res = await client.post(
        "/api/scripts/catalog",
        json={
            "script_id": script_id,
            "name": "Hardening test script",
            "category": "threat_hunting",
            "language": "bash",
            "script_content": "echo hello-from-sandbox",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["approved"] is False
    return script_id


@pytest.mark.asyncio
async def test_sandbox_execute_requires_authentication(client):
    """No bearer token at all -> 401, not a silent host-level execution."""
    headers = await _root_admin_headers(client)
    script_id = await _upload_script(client, headers)

    res = await client.post(
        f"/api/scripts/{script_id}/sandbox-execute",
        json={"script_id": script_id, "operator_id": "anon", "container_name": "whatever"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_sandbox_execute_rejects_unapproved_script(client):
    """Freshly-uploaded scripts default to approved=false and must not be runnable yet."""
    headers = await _root_admin_headers(client)
    script_id = await _upload_script(client, headers)

    res = await client.post(
        f"/api/scripts/{script_id}/sandbox-execute",
        json={"script_id": script_id, "operator_id": _ROOT_USERNAME, "container_name": "fake-container"},
        headers=headers,
    )
    assert res.status_code == 403
    assert "not approved" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sandbox_execute_rejects_unsupported_language(client):
    headers = await _root_admin_headers(client)
    script_id = _uniq("test-script-lang")
    res = await client.post(
        "/api/scripts/catalog",
        json={
            "script_id": script_id,
            "name": "Bad language",
            "category": "threat_hunting",
            "language": "powershell",
            "script_content": "Write-Host hi",
        },
    )
    assert res.status_code == 201
    approve = await client.post(f"/api/scripts/catalog/{script_id}/approve")
    assert approve.status_code == 200

    res = await client.post(
        f"/api/scripts/{script_id}/sandbox-execute",
        json={"script_id": script_id, "operator_id": _ROOT_USERNAME, "container_name": "fake-container"},
        headers=headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_sandbox_execute_approved_script_queues_and_fails_gracefully_without_docker(client):
    """
    Approved + authenticated + supported language: the request itself must
    succeed (queued), and since no real sandbox container exists in this
    test environment, the background execution must resolve to a clean
    "failure" execution record (VMOrchestrator reporting docker
    unavailable / container not found) rather than raising, hanging, or
    ever touching a host subprocess.
    """
    import asyncio

    headers = await _root_admin_headers(client)
    script_id = await _upload_script(client, headers)
    approve = await client.post(f"/api/scripts/catalog/{script_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    res = await client.post(
        f"/api/scripts/{script_id}/sandbox-execute",
        json={"script_id": script_id, "operator_id": _ROOT_USERNAME, "container_name": "nonexistent-sandbox"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    execution_id = res.json()["execution_id"]
    assert res.json()["status"] == "queued"

    # BackgroundTasks run after the response is sent; poll briefly.
    for _ in range(20):
        result = await client.get(f"/api/scripts/executions/{execution_id}/result")
        assert result.status_code == 200
        status = result.json()["status"]
        if status not in ("queued", "executing"):
            break
        await asyncio.sleep(0.1)

    final = result.json()
    assert final["status"] == "failure"
    assert final["stdout"] is None or final["stdout"] == ""


@pytest.mark.asyncio
async def test_script_catalog_list_and_get_are_real_db_reads(client):
    headers = await _root_admin_headers(client)
    script_id = await _upload_script(client, headers)

    listing = await client.get("/api/scripts/catalog")
    assert listing.status_code == 200
    ids = [s["script_id"] for s in listing.json()["scripts"]]
    assert script_id in ids

    detail = await client.get(f"/api/scripts/catalog/{script_id}")
    assert detail.status_code == 200
    assert detail.json()["script_content"] == "echo hello-from-sandbox"
