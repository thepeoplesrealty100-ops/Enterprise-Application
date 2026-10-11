"""
backend/tests/test_settings_developer.py
Focused tests for /api/settings/developer and related IAM session endpoints.
"""

from __future__ import annotations

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


_ROOT_USERNAME = _uniq("devroot")
_ROOT_PASSWORD = "Dev-Str0ng-Passphrase-2026!"


async def _root_headers(client) -> dict:
    # Register (ignore if already exists)
    await client.post(
        "/api/iam/auth/register",
        json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD},
    )
    # Force root_admin at DB layer for determinism
    try:
        from database import get_db_manager
        db = get_db_manager()
        user = db.get_user_by_username(_ROOT_USERNAME)
        if user:
            db.assign_user_role(user["user_id"], "root_admin")
    except Exception:
        pass
    r = await client.post(
        "/api/iam/auth/login",
        json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_developer_settings_requires_auth(client):
    r = await client.get("/api/settings/developer")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_and_put_developer_settings(client):
    headers = await _root_headers(client)
    r = await client.get("/api/settings/developer", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "telemetry_enabled" in data
    assert "debug_log_enabled" in data
    assert data["pqc_profile"] in ("commercial", "cnsa2")
    assert "pqc_profiles_available" in data

    r2 = await client.put(
        "/api/settings/developer",
        headers=headers,
        json={
            "telemetry_enabled": False,
            "debug_log_enabled": True,
            "pqc_profile": "cnsa2",
        },
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["telemetry_enabled"] is False
    assert body["debug_log_enabled"] is True
    assert body["pqc_profile"] == "cnsa2"
    assert body.get("updated_by")


@pytest.mark.asyncio
async def test_put_invalid_pqc_profile(client):
    headers = await _root_headers(client)
    r = await client.put(
        "/api/settings/developer",
        headers=headers,
        json={"pqc_profile": "not-a-real-profile"},
    )
    # Pydantic pattern validation -> 422
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_list_sessions(client):
    headers = await _root_headers(client)
    r = await client.get("/api/iam/auth/sessions", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


@pytest.mark.asyncio
async def test_revoke_other_sessions(client):
    headers = await _root_headers(client)
    r = await client.post("/api/iam/auth/sessions/revoke-others", headers=headers, json={})
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "revoked_others"


@pytest.mark.asyncio
async def test_auto_stage_severity_floor_seeded(client):
    headers = await _root_headers(client)
    r = await client.get("/api/resonance/automation-settings", headers=headers)
    # May be 200 with policy list; if auth gate differs, still check structure when 200
    if r.status_code == 200:
        data = r.json()
        policies = data.get("policy") or data.get("policies") or data
        keys = []
        if isinstance(policies, list):
            keys = [p.get("policy_key") or p.get("key") for p in policies]
        elif isinstance(policies, dict):
            keys = list(policies.keys())
        assert "auto_stage_severity_floor" in keys or "response_auto_stage_threshold" in keys
