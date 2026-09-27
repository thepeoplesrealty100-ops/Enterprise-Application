"""
backend/tests/test_compliance_intelligence.py

Regression + wiring tests for routers/compliance_intelligence.py after
the rewrite that replaced 23 fake fixture endpoints with a small real
surface delegating to the existing ComplianceAxiom service.

The important assertions here are the ones that would fail if the fake
version ever came back: /assess against an unknown framework must be
rejected (the old version echoed whatever framework string you sent),
and /reports/{id} against a nonexistent id must be 404 (the old version
would have returned a canned success). The rest is normal wiring.

Run: cd backend && python -m pytest tests/test_compliance_intelligence.py -q
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


_ROOT_USERNAME = _uniq("compliroot")
_ROOT_PASSWORD = "Compli-Root-Str0ng-Passphrase-2026!"


async def _root_admin_headers(client) -> dict:
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    user = get_db_manager().get_user_by_username(_ROOT_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_frameworks_returns_real_axiom_taxonomies(client):
    """The old /scoring endpoint accepted any framework string and echoed it.
    The real endpoint returns the actual FRAMEWORKS dict from
    security_agents.compliance_axiom."""
    res = await client.get("/api/compliance-intelligence/frameworks")
    assert res.status_code == 200
    body = res.json()
    assert set(body["frameworks"].keys()) == {"SOC2", "HIPAA", "NIST_CSF", "GDPR"}
    assert body["source"] == "security_agents.compliance_axiom.FRAMEWORKS"


@pytest.mark.asyncio
async def test_assess_rejects_unknown_framework(client):
    """The old fake echoed any framework name. The real one refuses."""
    headers = await _root_admin_headers(client)
    res = await client.post(
        "/api/compliance-intelligence/assess",
        json={"framework": "PRETEND_FRAMEWORK_XYZ"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "PRETEND_FRAMEWORK_XYZ".lower() in res.text.lower() or "unknown" in res.text.lower()


@pytest.mark.asyncio
async def test_assess_persists_report_visible_in_list(client):
    """End-to-end: run a real assessment, then verify it appears in the
    real compliance_reports table via the /reports listing."""
    headers = await _root_admin_headers(client)
    # Snapshot findings (no scope_id => uses caller-supplied list).
    res = await client.post(
        "/api/compliance-intelligence/assess",
        json={
            "framework": "NIST_CSF",
            # Uppercase severities required by the input-validation
            # middleware (see middleware/security_hardening.py's regex).
            "findings": [
                {"title": "test-finding-1", "severity": "HIGH", "source": "pentest_finding"},
                {"title": "test-finding-2", "severity": "LOW", "source": "pentest_finding"},
            ],
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    report_id = body.get("report_id")
    assert report_id is not None, "generate_report should have persisted and returned a report_id"
    assert body["framework"] == "NIST_CSF"
    assert body["findings_evaluated"] == 2
    assert body["findings_source"] == "explicit"

    listing = await client.get("/api/compliance-intelligence/reports?framework=NIST_CSF&limit=100")
    assert listing.status_code == 200
    ids = {r["report_id"] for r in listing.json()["reports"]}
    assert report_id in ids


@pytest.mark.asyncio
async def test_report_markdown_export_uses_real_axiom_formatter(client):
    """The .md endpoint runs the real ComplianceAxiom.to_markdown()."""
    headers = await _root_admin_headers(client)
    res = await client.post(
        "/api/compliance-intelligence/assess",
        json={"framework": "SOC2", "findings": []},
        headers=headers,
    )
    report_id = res.json()["report_id"]

    md = await client.get(f"/api/compliance-intelligence/reports/{report_id}?format=md")
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    # to_markdown emits a real H1 header with the framework name
    assert "Compliance Coverage Report" in md.text
    assert "SOC2" in md.text


@pytest.mark.asyncio
async def test_unknown_report_id_returns_honest_404(client):
    """The old fake always returned success. Real one must 404 for a
    missing id."""
    res = await client.get("/api/compliance-intelligence/reports/99999999")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_summary_reads_real_tables_not_fixtures(client):
    """The old /risk-dashboard invented six domain scores. The real summary
    reports whatever is actually in compliance_reports and findings."""
    res = await client.get("/api/compliance-intelligence/summary")
    assert res.status_code == 200
    body = res.json()
    # Every framework listed, either null or a real report_id
    assert set(body["latest_reports_by_framework"].keys()) == {"SOC2", "HIPAA", "NIST_CSF", "GDPR"}
    assert isinstance(body["findings_total"], int)
    assert isinstance(body["findings_by_severity"], dict)
    # No invented "0.94" score anywhere
    assert "overall_score" not in body


@pytest.mark.asyncio
async def test_assess_requires_authentication(client):
    """The old fake had no auth. The real one requires response:manage."""
    res = await client.post(
        "/api/compliance-intelligence/assess",
        json={"framework": "NIST_CSF"},
    )
    assert res.status_code == 401
