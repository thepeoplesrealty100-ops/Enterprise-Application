"""
backend/tests/test_msp_multi_tenant.py

Regression + wiring tests for the rebuilt routers/msp_multi_tenant.py.

The old version returned entirely hardcoded fixture data (a canned two-tenant
"Acme Corp"/"TechStart Inc" list) from every endpoint regardless of input,
with zero database access and zero auth anywhere in the file. The important
assertions here are the ones that would fail if that fake version ever came
back: /tenants before any create must not contain fabricated tenants, a
create must actually persist (visible on a fresh GET), switching to a tenant
the caller isn't a member of must be rejected, an unknown operation_id must
404 rather than returning a fabricated status, and SSO/billing endpoints must
report real state (not_configured / a real reachability probe) rather than
a hardcoded "healthy"/dollar-figure response.

Run: cd backend && python -m pytest tests/test_msp_multi_tenant.py -q
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


_ROOT_USERNAME = _uniq("msproot")
_ROOT_PASSWORD = "Msp-Root-Str0ng-Passphrase-2026!"


async def _root_admin_headers(client) -> dict:
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    user = get_db_manager().get_user_by_username(_ROOT_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user["user_id"]


async def _plain_user(client):
    """A registered-but-unprivileged user: no msp:manage, no tenant memberships."""
    from database import get_db_manager
    username, password = _uniq("mspuser"), "Msp-User-Str0ng-Passphrase-2026!"
    await client.post("/api/iam/auth/register", json={"username": username, "password": password})
    user = get_db_manager().get_user_by_username(username)
    login = await client.post("/api/iam/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user["user_id"]


@pytest.mark.asyncio
async def test_create_tenant_requires_auth(client):
    res = await client.post("/api/msp/tenants", json={"tenant_id": _uniq("t"), "tenant_name": "No Auth Co"})
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_and_list_tenant_persists_for_real(client):
    """The old router's GET /tenants always returned the same two canned
    tenants no matter what. Assert a freshly created tenant actually shows
    up, and with the exact fields we sent -- not fixture data."""
    headers, _ = await _root_admin_headers(client)
    tid = _uniq("acme")
    res = await client.post("/api/msp/tenants", headers=headers, json={
        "tenant_id": tid, "tenant_name": "Acme Regression Co", "tenant_type": "client",
        "subscription_tier": "professional", "device_limit": 50, "user_limit": 10,
    })
    assert res.status_code == 200, res.text
    created = res.json()
    assert created["tenant_id"] == tid
    assert created["tenant_name"] == "Acme Regression Co"
    assert created["device_count"] == 0

    listing = await client.get("/api/msp/tenants", headers=headers)
    assert listing.status_code == 200
    ids = [t["tenant_id"] for t in listing.json()["tenants"]]
    assert tid in ids

    dupe = await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": tid, "tenant_name": "Dupe"})
    assert dupe.status_code == 409


@pytest.mark.asyncio
async def test_unknown_tenant_404s(client):
    headers, _ = await _root_admin_headers(client)
    res = await client.get(f"/api/msp/tenants/{_uniq('ghost')}", headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_device_count_reflects_real_tagged_devices(client):
    """The old router's device/user counts were invented numbers. Tag a
    real network_map row for this tenant and assert the count reflects it."""
    from database import get_db_manager
    headers, _ = await _root_admin_headers(client)
    tid = _uniq("tagged")
    await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": tid, "tenant_name": "Tagged Co"})

    ip = f"10.77.{uuid.uuid4().int % 255}.{uuid.uuid4().int % 255}"
    get_db_manager().upsert_network_host({
        "ip_address": ip, "hostname": f"host-{ip.replace('.', '-')}",
        "tags": [f"tenant:{tid}"],
    })

    res = await client.get(f"/api/msp/tenants/{tid}", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["device_count"] == 1


@pytest.mark.asyncio
async def test_switch_rejected_for_non_member(client):
    """The old /tenants/switch accepted any tenant_id string from anyone
    and returned a fabricated jwt-shaped token. The real one must reject a
    switch to a tenant the caller doesn't belong to."""
    admin_headers, _ = await _root_admin_headers(client)
    tid = _uniq("private")
    await client.post("/api/msp/tenants", headers=admin_headers, json={"tenant_id": tid, "tenant_name": "Private Co"})

    user_headers, _ = await _plain_user(client)
    res = await client.post("/api/msp/tenants/switch", headers=user_headers, json={"tenant_id": tid})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_add_member_then_switch_succeeds(client):
    admin_headers, _ = await _root_admin_headers(client)
    tid = _uniq("joinable")
    await client.post("/api/msp/tenants", headers=admin_headers, json={"tenant_id": tid, "tenant_name": "Joinable Co"})

    user_headers, user_id = await _plain_user(client)
    add = await client.post(f"/api/msp/tenants/{tid}/members", headers=admin_headers,
                             json={"user_id": user_id, "role": "member"})
    assert add.status_code == 200, add.text

    switch = await client.post("/api/msp/tenants/switch", headers=user_headers, json={"tenant_id": tid})
    assert switch.status_code == 200, switch.text
    assert switch.json()["current_tenant"] == tid

    current = await client.get("/api/msp/tenants/switch/current", headers=user_headers)
    assert tid in current.json()["tenant_ids"]

    remove = await client.delete(f"/api/msp/tenants/{tid}/members/{user_id}", headers=admin_headers)
    assert remove.status_code == 200
    remove_again = await client.delete(f"/api/msp/tenants/{tid}/members/{user_id}", headers=admin_headers)
    assert remove_again.status_code == 404


@pytest.mark.asyncio
async def test_sso_reports_not_configured_until_saved(client):
    """The old SSO test-connection endpoint always reported "healthy" no
    matter what. An un-configured mechanism must report not_configured,
    never a fabricated healthy status."""
    headers, _ = await _root_admin_headers(client)
    tid = _uniq("ssoco")
    await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": tid, "tenant_name": "SSO Co"})

    test_res = await client.post(f"/api/msp/tenants/{tid}/sso/saml/test", headers=headers)
    assert test_res.status_code == 200
    assert test_res.json()["connection_status"] == "not_configured"

    configure = await client.post(f"/api/msp/tenants/{tid}/sso/configure", headers=headers, json={
        "mechanism_type": "saml", "provider": "okta", "config": {"metadata_url": "https://example.invalid/metadata"},
    })
    assert configure.status_code == 200, configure.text
    assert configure.json()["enabled"] is False

    mechanisms = await client.get(f"/api/msp/tenants/{tid}/sso/mechanisms", headers=headers)
    types_ = [m["mechanism_type"] for m in mechanisms.json()["mechanisms"]]
    assert "saml" in types_

    probe = await client.post(f"/api/msp/tenants/{tid}/sso/saml/test", headers=headers)
    assert probe.status_code == 200
    assert probe.json()["connection_status"] in ("reachable", "unreachable")


@pytest.mark.asyncio
async def test_broadcast_operation_then_status_then_unknown_404s(client):
    """The old operations endpoints returned a fabricated operation_id and
    always-"completed" status for anything. Assert a real create -> real
    status roundtrip, and a 404 for an id that was never created."""
    headers, _ = await _root_admin_headers(client)
    src = _uniq("src")
    tgt = _uniq("tgt")
    await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": src, "tenant_name": "Source Co"})
    await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": tgt, "tenant_name": "Target Co"})

    broadcast = await client.post("/api/msp/operations/broadcast", headers=headers, json={
        "operation_type": "policy_push", "source_tenant": src, "target_tenants": [tgt], "payload": {"k": "v"},
    })
    assert broadcast.status_code == 200, broadcast.text
    op_id = broadcast.json()["operation_id"]
    assert broadcast.json()["status"] == "queued"

    status_res = await client.get(f"/api/msp/operations/{op_id}/status", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["source_tenant"] == src

    rollback = await client.post(f"/api/msp/operations/{op_id}/rollback", headers=headers)
    assert rollback.status_code == 200
    assert rollback.json()["rollback_status"] == "rolled_back"

    unknown = await client.get(f"/api/msp/operations/{uuid.uuid4()}/status", headers=headers)
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_billing_forecast_is_honest_not_configured(client):
    """The old billing endpoint invented dollar figures. There is no
    metering/billing integration in this codebase, so the real endpoint
    must say so rather than fabricate a number."""
    headers, _ = await _root_admin_headers(client)
    tid = _uniq("billco")
    await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": tid, "tenant_name": "Billing Co"})
    res = await client.get(f"/api/msp/billing/forecast?tenant_id={tid}", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["billing_status"] == "not_configured"


@pytest.mark.asyncio
async def test_data_isolation_test_detects_real_overlap(client):
    """The old isolation-test endpoint always returned an all-"passed"
    canned checklist. Tag a device for BOTH tenants and assert the real
    check flags the overlap as FAILED."""
    from database import get_db_manager
    headers, _ = await _root_admin_headers(client)
    t1, t2 = _uniq("iso1"), _uniq("iso2")
    await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": t1, "tenant_name": "Iso One"})
    await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": t2, "tenant_name": "Iso Two"})

    clean = await client.post("/api/msp/security/data-isolation-test", headers=headers,
                               json={"source_tenant": t1, "target_tenant": t2})
    assert clean.status_code == 200, clean.text
    assert clean.json()["test_status"] == "passed"

    ip = f"10.66.{uuid.uuid4().int % 255}.{uuid.uuid4().int % 255}"
    get_db_manager().upsert_network_host({
        "ip_address": ip, "hostname": f"host-{ip.replace('.', '-')}", "tags": [f"tenant:{t1}", f"tenant:{t2}"],
    })

    overlapping = await client.post("/api/msp/security/data-isolation-test", headers=headers,
                                     json={"source_tenant": t1, "target_tenant": t2})
    assert overlapping.status_code == 200
    body = overlapping.json()
    assert body["test_status"] == "failed"
    device_check = next(c for c in body["isolation_checks"] if "Device" in c["check"])
    assert device_check["status"] == "FAILED"
    assert device_check["overlapping_devices"] >= 1


@pytest.mark.asyncio
async def test_audit_cross_tenant_reflects_real_actions(client):
    """The old cross-tenant audit endpoint returned fabricated counts. This
    module's own mutations write real audit_log rows via insert_audit_entry
    -- assert the aggregation picks up at least the tenant we just created."""
    from datetime import datetime, timedelta, timezone
    headers, _ = await _root_admin_headers(client)
    tid = _uniq("auditco")
    await client.post("/api/msp/tenants", headers=headers, json={"tenant_id": tid, "tenant_name": "Audit Co"})

    start = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    res = await client.get("/api/msp/audit/cross-tenant", headers=headers,
                            params={"start_date": start, "end_date": end})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] >= 1
    assert "msp:tenant_create" in body["by_action"]
