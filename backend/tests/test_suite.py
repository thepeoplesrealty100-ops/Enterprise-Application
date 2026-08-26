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
    """POST /api/pentest/scan with no target should return 422."""
    response = await client.post("/api/pentest/scan", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pentest_start_valid(client):
    """POST /api/pentest/scan should accept a valid target and return 202."""
    response = await client.post(
        "/api/pentest/scan",
        json={"target": "192.0.2.1", "scan_type": "quick", "operator_id": "test"},
    )
    # 202 Accepted (scan queued) or 422 if schema changed
    assert response.status_code in (202, 200)
    data = response.json()
    assert "test_id" in data
    assert data["status"] == "queued"


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


# ---------------------------------------------------------------------------
# Repository unit tests (no HTTP)
# ---------------------------------------------------------------------------

def test_scan_repository_lifecycle():
    from repository import ScanRepository  # noqa: PLC0415
    repo = ScanRepository()

    record = repo.create_scan("10.0.0.1", "comprehensive", "operator-1")
    assert record["status"] == "queued"

    scan_id = record["scan_id"]
    updated = repo.update_scan_status(scan_id, "running")
    assert updated["status"] == "running"

    fetched = repo.get_scan(scan_id)
    assert fetched is not None
    assert fetched["status"] == "running"

    repo.delete_scan(scan_id)
    assert repo.get_scan(scan_id) is None


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
