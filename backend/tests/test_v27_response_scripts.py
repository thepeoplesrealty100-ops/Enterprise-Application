"""
backend/tests/test_v27_response_scripts.py
JAKAL v2.7 — Detection & Response + Script Catalog + MFA QR test suite.

Run: cd backend && python -m pytest tests/test_v27_response_scripts.py -q

See test_v26_settings_security.py's module docstring for why this file
manages its own root_admin identity via a direct DB role grant rather than
assuming "first registration wins" — same shared-on-disk-DB rationale.
"""

import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
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


_ROOT_USERNAME = _uniq("v27root")
_ROOT_PASSWORD = "V27Root-Str0ng-Passphrase-2026!"


async def _root_admin_headers(client) -> dict:
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    user = get_db_manager().get_user_by_username(_ROOT_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_scope(target_cidr: str = "203.0.113.0/24"):
    from database import get_db_manager
    db = get_db_manager()
    now = datetime.now(timezone.utc)
    db.add_scope("v27-test", target_cidr, now - timedelta(days=1), now + timedelta(days=30))
    db.add_insurance_policy(f"V27-POL-{now.timestamp()}", "Test Underwriter", 1_000_000, now + timedelta(days=365))


# ---------------------------------------------------------------------------
# Script catalog — pure read, real files
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_script_catalog_indexes_real_files(client):
    stats = await client.get("/api/cheatsheet/scripts/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total_scripts"] > 0
    assert "LOW" in body["by_risk"] or "MEDIUM" in body["by_risk"]

    listing = await client.get("/api/cheatsheet/scripts?phase=recon_passive")
    assert listing.status_code == 200
    scripts = listing.json()["scripts"]
    assert len(scripts) > 0
    assert all(s["phase"] == "recon_passive" for s in scripts)
    # Content is never in the list response — only in the single-entry GET.
    assert "content" not in scripts[0]

    detail = await client.get(f"/api/cheatsheet/scripts/{scripts[0]['id']}")
    assert detail.status_code == 200
    assert "content" in detail.json()
    assert len(detail.json()["content"]) > 0


@pytest.mark.asyncio
async def test_unknown_script_id_404s(client):
    response = await client.get("/api/cheatsheet/scripts/does-not-exist-xyz")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Script staging — authorization-gated, approval-gated, never auto-executes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stage_script_requires_authorized_scope(client):
    headers = await _root_admin_headers(client)
    listing = await client.get("/api/cheatsheet/scripts?risk_level=LOW")
    script_id = listing.json()["scripts"][0]["id"]

    # No scope seeded for this made-up target -> authorization gate denies.
    unauthorized_target = f"unauthorized-{uuid.uuid4().hex[:8]}.example.invalid"
    denied = await client.post(f"/api/cheatsheet/scripts/{script_id}/stage",
                                json={"target": unauthorized_target}, headers=headers)
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_stage_and_approve_script_then_content_mismatch_is_rejected(client):
    """
    Full staging lifecycle against an authorized target, then proves the
    run-in-sandbox endpoint's content-hash check actually matters: it
    must reject execution if given someone else's approval_request_id.
    """
    headers = await _root_admin_headers(client)
    await _seed_scope()
    listing = await client.get("/api/cheatsheet/scripts?risk_level=LOW")
    scripts = listing.json()["scripts"]
    assert len(scripts) >= 2
    script_a, script_b = scripts[0], scripts[1]

    staged = await client.post(f"/api/cheatsheet/scripts/{script_a['id']}/stage",
                                json={"target": "203.0.113.10"}, headers=headers)
    assert staged.status_code == 200
    approval_request_id = staged.json()["approval_request_id"]
    assert staged.json()["status"] == "staged"

    approve = await client.post(f"/api/approval/{approval_request_id}/approve",
                                 json={"operator_id": _ROOT_USERNAME, "reason": "test"}, headers=headers)
    assert approve.status_code == 200

    # Using script_a's approval to run script_b must be rejected (409) —
    # this is exactly the guard that stops a stale/mismatched approval
    # from being replayed against different content.
    mismatched = await client.post(
        f"/api/cheatsheet/scripts/{script_b['id']}/run-in-sandbox",
        json={"approval_request_id": approval_request_id, "container_name": "does-not-exist"},
        headers=headers,
    )
    assert mismatched.status_code == 409

    # Running the correct script against a sandbox that doesn't exist
    # fails cleanly (no docker daemon in CI) rather than crashing — proves
    # the approval+hash checks passed and it reached the VM orchestrator call.
    correct = await client.post(
        f"/api/cheatsheet/scripts/{script_a['id']}/run-in-sandbox",
        json={"approval_request_id": approval_request_id, "container_name": "does-not-exist"},
        headers=headers,
    )
    assert correct.status_code == 200
    assert correct.json()["status"] in ("error",)  # docker unavailable / sandbox not found in CI


# ---------------------------------------------------------------------------
# Detection & Response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_triage_low_severity_does_not_auto_stage(client):
    response = await client.post("/api/response/triage", json={
        "finding_summary": "self-signed certificate on an internal dev box",
        "threat_category": "misconfiguration",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["severity"] < 0.8
    assert body["auto_staged_approval_request_id"] is None


@pytest.mark.asyncio
async def test_triage_critical_severity_auto_stages_containment(client):
    response = await client.post("/api/response/triage", json={
        "finding_summary": "unauthenticated RCE actively exploited in the wild, domain admin obtained",
        "threat_category": "ransomware",
        "target": "203.0.113.20",
        "operator_id": "v27-triage-test",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["severity"] >= 0.8
    assert body["auto_staged_approval_request_id"] is not None
    assert len(body["recommended_playbooks"]) > 0
    # The ransomware_containment playbook (added in edr_mdr.py) should surface here.
    assert any(p["key"] == "ransomware_containment" for p in body["recommended_playbooks"])


@pytest.mark.asyncio
async def test_ioc_block_and_list(client):
    headers = await _root_admin_headers(client)
    indicator = f"198.51.100.{uuid.uuid4().int % 250}"
    blocked = await client.post("/api/response/ioc/block",
                                 json={"indicator": indicator, "indicator_type": "ip", "reason": "test block"},
                                 headers=headers)
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"

    listed = await client.get("/api/response/ioc")
    assert listed.status_code == 200
    assert any(i["indicator"] == indicator for i in listed.json()["indicators"])


@pytest.mark.asyncio
async def test_quarantine_artifact_is_immediate_host_requires_approval(client):
    headers = await _root_admin_headers(client)
    artifact = await client.post("/api/response/quarantine",
                                  json={"target": "payload-exec-123", "target_type": "artifact", "reason": "test"},
                                  headers=headers)
    assert artifact.status_code == 200
    assert artifact.json()["status"] == "quarantined"

    await _seed_scope("203.0.113.0/24")
    host = await client.post("/api/response/quarantine",
                              json={"target": "203.0.113.30", "target_type": "host", "reason": "test host quarantine"},
                              headers=headers)
    assert host.status_code == 200
    assert host.json()["status"] == "staged"
    assert "approval_request_id" in host.json()


@pytest.mark.asyncio
async def test_isolate_host_always_staged_never_auto_executes(client):
    headers = await _root_admin_headers(client)
    await _seed_scope("203.0.113.0/24")
    response = await client.post("/api/response/isolate-host",
                                  json={"target": "203.0.113.40", "reason": "confirmed lateral movement"},
                                  headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "staged"
    assert body["d3fend_technique"] == "D3-NI"

    # The action is NOT marked completed/executed by the staging call itself.
    actions = await client.get("/api/response/actions?action_type=isolate_host_staged&limit=5")
    assert actions.status_code == 200
    assert any(a["status"] == "staged" for a in actions.json()["actions"])


@pytest.mark.asyncio
async def test_response_stats_endpoint(client):
    response = await client.get("/api/response/stats")
    assert response.status_code == 200
    assert "total" in response.json()


@pytest.mark.asyncio
async def test_compliance_pre_check_no_longer_500s(client):
    """
    Regression test: GET /compliance/pre-check used to query
    global_security_settings for columns ("setting_key", "data") that
    never existed on that table, throwing a BinderException on every
    call. Now backed by the real org_compliance_posture table.
    """
    response = await client.get(
        "/api/response/compliance/pre-check",
        params={"action_type": "isolate_host_staged", "target": "10.0.0.5"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["compliant"] is True
    assert body["violations"] == []


@pytest.mark.asyncio
async def test_compliance_posture_set_then_gates_pre_check(client):
    headers = await _root_admin_headers(client)

    put_res = await client.put(
        "/api/response/compliance/posture",
        json={"frameworks": ["HIPAA"], "hipaa_allowed_regions": ["us-east"]},
        headers=headers,
    )
    assert put_res.status_code == 200
    assert put_res.json()["posture"]["frameworks"] == ["HIPAA"]

    get_res = await client.get("/api/response/compliance/posture")
    assert get_res.status_code == 200
    assert get_res.json()["posture"]["hipaa_allowed_regions"] == ["us-east"]

    blocked = await client.get(
        "/api/response/compliance/pre-check",
        params={"action_type": "isolate_host_staged", "target": "eu-db-prod"},
    )
    assert blocked.status_code == 200
    body = blocked.json()
    assert body["compliant"] is False
    assert any(v["constraint"] == "hipaa_data_residency" for v in body["violations"])

    # Reset posture so this test doesn't leak state into others sharing
    # the on-disk demo DB.
    await client.put("/api/response/compliance/posture", json={}, headers=headers)


@pytest.mark.asyncio
async def test_compliance_posture_write_requires_auth(client):
    response = await client.put("/api/response/compliance/posture", json={"frameworks": ["HIPAA"]})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# MFA QR code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mfa_enroll_returns_scannable_qr(client):
    headers = await _root_admin_headers(client)
    response = await client.post("/api/iam/auth/mfa/enroll", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["qr_data_uri"] is not None
    assert body["qr_data_uri"].startswith("data:image/svg+xml;base64,")

    import base64
    svg = base64.b64decode(body["qr_data_uri"].split(",", 1)[1]).decode("utf-8")
    assert "<svg" in svg
