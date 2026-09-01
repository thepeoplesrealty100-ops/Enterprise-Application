"""
backend/tests/test_suite.py
JAKAL API test suite — uses pytest + httpx AsyncClient.

Run with:
    pytest backend/tests/test_suite.py -v
"""

import sys
import types
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

# Run from inside backend/ (matches how app.py imports its modules).
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
# Stub the optional LLM SDK so the app imports cleanly in CI/offline.
sys.modules.setdefault("anthropic", types.ModuleType("anthropic"))

# ---------------------------------------------------------------------------
# App import (lazy so tests don't fail if optional deps are absent)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from app import app as _app  # noqa: PLC0415
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


# ---------------------------------------------------------------------------
# Schema validation — PentestRunRequest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pentest_start_missing_target(client):
    """
    POST /api/pentest/run with no target should return 422.

    Fixed: this used to POST to /api/pentest/scan, a path that doesn't
    exist in routers/pentest.py (only POST /pentest/run is defined) — so
    every assertion here was really asserting against a bare FastAPI
    "route not found" 404, not the pentest router's own validation.
    """
    response = await client.post("/api/pentest/run", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pentest_start_valid(client, app):
    """
    POST /api/pentest/run with a valid target completes synchronously and
    returns the finished report (this pipeline is deliberately not an
    async job queue — see routers/pentest.py's module docstring — so
    "queued" is not part of its contract; fixed to match the real
    PentestResponse shape instead of an older async-job assumption).

    Also fixed: every network-facing agent call goes through
    tools.authorization.check_authorization_and_scope() (by design — see
    that module's docstring), which denies with 403 unless an active
    scope + insurance policy covers the target. This test was asserting
    against that 403 without ever seeding one, so it only "passed" by
    accident on whichever machine/run order happened to leave a prior
    test's scope lying around in the shared on-disk DB. Seed a real scope
    covering 192.0.2.1 explicitly so this test is self-contained.
    """
    from datetime import datetime, timezone, timedelta
    from database import get_db_manager
    db = get_db_manager()
    now = datetime.now(timezone.utc)
    db.add_scope("test-suite", "192.0.2.0/24", now - timedelta(days=1), now + timedelta(days=30))
    db.add_insurance_policy(f"TS-{now.timestamp()}", "Test Underwriter", 1_000_000, now + timedelta(days=365))

    response = await client.post(
        "/api/pentest/run",
        json={"target": "192.0.2.1", "scan_type": "quick", "operator_id": "test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "test_id" in data
    assert data["status"] == "report_ready"
    assert "report_markdown" in data


@pytest.mark.asyncio
async def test_pentest_get_nonexistent(client):
    """GET /api/pentest/scan/<bad-id> should return 404."""
    response = await client.get("/api/pentest/scan/does-not-exist")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Quantum
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quantum_status(client):
    """GET /api/quantum/status should always return 200."""
    response = await client.get("/api/quantum/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ready", "unavailable")


@pytest.mark.asyncio
async def test_quantum_job_survives_restart(client):
    """
    Regression test: QuantumEngine.store_result() only ever kept an
    in-process dict (job_cache); quantum_jobs existed in the schema but
    nothing wrote to it, so job history was unqueryable via SQL and lost
    on restart despite the table's own purpose. GET /jobs/{id} now falls
    back to database.py's get_quantum_job() when the in-memory engine
    doesn't have it -- simulate "after a restart" by querying the DB
    directly instead of going through the same process's cache.
    """
    submit = await client.post(
        "/api/quantum/submit",
        json={"circuit": "bell_state", "shots": 50, "backend": "qiskit_aer", "operator_id": "tester"},
    )
    assert submit.status_code == 200
    job_id = submit.json()["job_id"]

    from database import get_db_manager
    db_row = get_db_manager().get_quantum_job(job_id)
    assert db_row is not None
    assert db_row.get("status") == "completed"

    # The real endpoint must also resolve it (cache hit in this process,
    # but the DB fallback is exercised above independently).
    fetched = await client.get(f"/api/quantum/jobs/{job_id}")
    assert fetched.status_code == 200


# ---------------------------------------------------------------------------
# Reports — aggregate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reports_aggregate(client):
    """POST /api/reports/aggregate with minimal payload."""
    response = await client.post(
        "/api/reports/aggregate",
        json={
            "scan_id": "test-scan-001",
            "results": [
                {
                    "tool":     "nmap",
                    "target":   "192.0.2.1",
                    "findings": [],
                }
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["scan_id"] == "test-scan-001"
    assert data["total_findings"] == 0


# NOTE: a `test_scan_repository_lifecycle` test previously lived here,
# importing `from repository import ScanRepository`. No such module has
# existed anywhere in this codebase for a while now (grep confirms
# `ScanRepository` appeared nowhere but this one test) — pentest scan
# persistence goes straight through DuckDBManager.insert_pentest()
# (see routers/pentest.py), no repository abstraction layer was ever
# built. Removed rather than resurrecting a module nothing else uses,
# since the real contract is already covered by test_pentest_start_valid
# below and backend/tests/test_v25_ares_integration.py's DB-level tests.


# ---------------------------------------------------------------------------
# Wrapper unit tests (no network)
# ---------------------------------------------------------------------------

def test_sanitize_target_valid():
    from wrappers.base import sanitize_target
    assert sanitize_target("192.168.1.1") == "192.168.1.1"
    assert sanitize_target("staging.example.com") == "staging.example.com"
    assert sanitize_target("https://example.com:8080") == "https://example.com:8080"


def test_sanitize_target_injection():
    from wrappers.base import sanitize_target
    import pytest as _pytest
    with _pytest.raises(ValueError):
        sanitize_target("192.168.1.1; rm -rf /")
    with _pytest.raises(ValueError):
        sanitize_target("$(whoami)")
    with _pytest.raises(ValueError):
        sanitize_target("../../etc/passwd")


def test_reports_wrapper_summary():
    from wrappers.reports_wrapper import ReportsWrapper
    wrapper = ReportsWrapper()
    results = [
        {
            "tool": "nmap",
            "target": "10.0.0.1",
            "findings": [
                {"severity": "high", "name": "Open SSH", "port": 22},
            ],
        },
        {
            "tool": "nuclei",
            "target": "10.0.0.1",
            "findings": [
                {"severity": "critical", "name": "CVE-2024-0001"},
            ],
        },
    ]
    summary = wrapper.generate_summary("scan-abc", results)
    assert summary["total_findings"] == 2
    assert summary["risk_score"] == 17   # high=7 + critical=10
    assert len(summary["high_priority"]) == 2
