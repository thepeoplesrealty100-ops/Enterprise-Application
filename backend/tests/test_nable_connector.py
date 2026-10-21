"""
Tests for routers/nable.py -- the N-able network-intelligence connector.

Covers: the webhook is never open (secret or user auth required), ingest ->
list -> ack -> resolve lifecycle against the real DuckDB tables, input
validation, 404 on unknown alerts, and the honest "not connected" status on
an empty install.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

_PASSWORD = "Nable-Test-Str0ng-Passphrase-2026!"
_SECRET = "test-nable-secret-" + uuid.uuid4().hex


@pytest.fixture(scope="module")
def app():
    from app import app as _app
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _auth_headers(client) -> dict:
    from database import get_db_manager
    name = f"nable-{uuid.uuid4().hex[:10]}"
    await client.post("/api/iam/auth/register", json={"username": name, "password": _PASSWORD})
    user = get_db_manager().get_user_by_username(name)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": name, "password": _PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _alert(**over):
    base = {
        "severity": "HIGH", "alert_type": "c2_callback", "source_ip": "10.20.30.40",
        "dest_ip": "203.0.113.9", "dest_port": 443, "bytes_transferred": 4096,
        "description": "Beaconing to known C2", "device_name": "ws-014",
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_webhook_is_never_open(client, monkeypatch):
    monkeypatch.delenv("NABLE_WEBHOOK_SECRET", raising=False)
    res = await client.post("/api/nable/webhook", json=_alert())
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_webhook_secret_enforced_and_lifecycle(client, monkeypatch):
    monkeypatch.setenv("NABLE_WEBHOOK_SECRET", _SECRET)

    bad = await client.post("/api/nable/webhook", json=_alert(), headers={"X-Nable-Secret": "wrong"})
    assert bad.status_code == 401

    ok = await client.post("/api/nable/webhook", json=_alert(), headers={"X-Nable-Secret": _SECRET})
    assert ok.status_code == 200, ok.text
    alert_id = ok.json()["alert_id"]

    headers = await _auth_headers(client)

    listed = await client.get("/api/nable/alerts", params={"state": "open"}, headers=headers)
    assert listed.status_code == 200
    found = [a for a in listed.json()["alerts"] if a["alert_id"] == alert_id]
    assert found and found[0]["severity"] == "HIGH"

    ack = await client.post(f"/api/nable/alerts/{alert_id}/ack", json={"notes": "looking"}, headers=headers)
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"

    res = await client.post(
        f"/api/nable/alerts/{alert_id}/resolve",
        json={"remediation": "host isolated", "action_taken": "edr isolate"}, headers=headers)
    assert res.status_code == 200 and res.json()["status"] == "resolved"

    after = await client.get("/api/nable/alerts", params={"state": "resolved"}, headers=headers)
    assert any(a["alert_id"] == alert_id for a in after.json()["alerts"])

    status = await client.get("/api/nable/status", headers=headers)
    assert status.status_code == 200 and status.json()["connected"] is True


@pytest.mark.asyncio
async def test_validation_and_not_found(client, monkeypatch):
    monkeypatch.setenv("NABLE_WEBHOOK_SECRET", _SECRET)
    hdr = {"X-Nable-Secret": _SECRET}

    assert (await client.post("/api/nable/webhook", json=_alert(severity="URGENT"), headers=hdr)).status_code in (400, 422)
    assert (await client.post("/api/nable/webhook", json=_alert(dest_port=70000), headers=hdr)).status_code in (400, 422)

    headers = await _auth_headers(client)
    assert (await client.get("/api/nable/alerts", params={"severity": "nope"}, headers=headers)).status_code == 400
    missing = await client.post("/api/nable/alerts/does-not-exist/ack", json={}, headers=headers)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_networks_require_valid_cidr_and_report_alert_counts(client, monkeypatch):
    headers = await _auth_headers(client)

    bad = await client.post("/api/nable/networks", json={"name": "x", "cidr": "not-a-cidr"}, headers=headers)
    assert bad.status_code == 400

    added = await client.post(
        "/api/nable/networks", json={"name": "HQ LAN", "cidr": "10.20.30.0/24", "location": "HQ"}, headers=headers)
    assert added.status_code == 200

    nets = await client.get("/api/nable/networks", headers=headers)
    assert nets.status_code == 200
    assert any(n["cidr"] == "10.20.30.0/24" for n in nets.json()["networks"])


@pytest.mark.asyncio
async def test_endpoints_require_auth(client):
    for path in ("/api/nable/alerts", "/api/nable/networks", "/api/nable/status"):
        assert (await client.get(path)).status_code in (401, 403), path
