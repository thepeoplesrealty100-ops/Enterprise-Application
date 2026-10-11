"""
backend/tests/test_fleet_management.py
Fleet Management (/api/fleet) — real inventory + gated containment.

Run: cd backend && python -m pytest tests/test_fleet_management.py -q

Covers the rewrite of routers/fleet_management.py, which previously
returned hardcoded device fixtures from every endpoint. The important
regression here is not "does it return data" but the containment gate:
POST /actions/isolate-device used to accept an unauthenticated request
and answer {"isolation_active": true, "network_access_blocked": true}
without creating an approval request, writing an audit row, or touching
anything -- a containment action that both lied and bypassed the
approval gate the rest of this platform is built around.
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


_ROOT_USERNAME = _uniq("fleetroot")
_ROOT_PASSWORD = "Fleet-Root-Str0ng-Passphrase-2026!"

# Inside TEST-NET-3 (RFC 5737), the same documentation range the other
# suites scope against -- never a routable host.
_SCOPE_CIDR = "203.0.113.0/24"
_DEVICE_IP = "203.0.113.77"


async def _root_admin_headers(client) -> dict:
    """Same direct role-grant approach as test_v27_response_scripts.py --
    see that module's docstring for why 'first registration wins' is not
    safe to assume against the shared on-disk demo DB."""
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    user = get_db_manager().get_user_by_username(_ROOT_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_device(ip: str = _DEVICE_IP, **overrides) -> int:
    """Insert a real network_map row and return its id."""
    from database import get_db_manager
    record = {
        "ip_address": ip,
        "hostname": overrides.get("hostname", "fleet-test-host"),
        "mac_address": "00:AA:BB:CC:DD:EE",
        "os_fingerprint": overrides.get("os_fingerprint", "Ubuntu 22.04 LTS (Linux 5.15)"),
        "open_ports": overrides.get("open_ports", [{"port": 22, "proto": "tcp", "service": "ssh"}]),
        "tags": overrides.get("tags", ["fleet-test"]),
        "risk_score": overrides.get("risk_score", 3.5),
    }
    return get_db_manager().upsert_network_host(record)


async def _seed_scope():
    from database import get_db_manager
    db = get_db_manager()
    now = datetime.now(timezone.utc)
    db.add_scope("fleet-test", _SCOPE_CIDR, now - timedelta(days=1), now + timedelta(days=30))
    db.add_insurance_policy(f"FLEET-POL-{now.timestamp()}", "Test Underwriter", 1_000_000, now + timedelta(days=365))


# ---------------------------------------------------------------------------
# Inventory — real rows, not fixtures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_devices_returns_real_inventory_not_fixtures(client):
    """
    The old implementation always returned the same three invented hosts
    (CORP-WS-001 / CORP-SRV-001 / LAPTOP-SMITH) regardless of database
    contents. Seed a real host and assert it appears -- and that the
    fixtures do not.
    """
    device_id = _seed_device()
    res = await client.get("/api/fleet/devices?limit=500")
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "network_map"

    ids = {d["device_id"] for d in body["devices"]}
    assert str(device_id) in ids

    names = {(d.get("hostname") or "") for d in body["devices"]}
    assert "CORP-WS-001" not in names
    assert "LAPTOP-SMITH" not in names


@pytest.mark.asyncio
async def test_device_detail_reports_real_fields_and_names_what_is_missing(client):
    device_id = _seed_device(ip="203.0.113.78", hostname="fleet-detail-host")
    res = await client.get(f"/api/fleet/devices/{device_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["device"]["hostname"] == "fleet-detail-host"
    assert body["device"]["ip_address"] == "203.0.113.78"
    # Host telemetry needs an agent this platform does not deploy; the
    # endpoint must say so rather than inventing CPU/RAM numbers.
    assert "unavailable" in body
    assert any("cpu" in f for f in body["unavailable"]["fields"])


@pytest.mark.asyncio
async def test_os_and_device_type_are_derived_from_real_fingerprint(client):
    device_id = _seed_device(
        ip="203.0.113.79",
        os_fingerprint="Microsoft Windows Server 2022",
        open_ports=[{"port": 443, "proto": "tcp", "service": "https"}],
        tags=[],
    )
    res = await client.get(f"/api/fleet/devices/{device_id}")
    assert res.status_code == 200
    device = res.json()["device"]
    assert device["os"] == "windows"
    # 443 open, no tag to go on -> server heuristic
    assert device["device_type"] == "server"


@pytest.mark.asyncio
async def test_unknown_device_404s(client):
    res = await client.get("/api/fleet/devices/99999999")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_device_health_is_posture_not_fabricated_host_metrics(client):
    device_id = _seed_device(ip="203.0.113.80", risk_score=9.5)
    res = await client.get(f"/api/fleet/devices/{device_id}/health")
    assert res.status_code == 200
    body = res.json()
    assert body["host_telemetry"]["available"] is False
    # risk_score 9.5 must trip the risk check, not report "healthy"
    assert body["posture"] == "at_risk"
    risk_check = [c for c in body["checks"] if c["check"].startswith("Risk score")][0]
    assert risk_check["status"] == "fail"


@pytest.mark.asyncio
async def test_groups_derive_from_real_tags(client):
    tag = _uniq("grp")
    _seed_device(ip="203.0.113.81", tags=[tag])
    res = await client.get("/api/fleet/groups")
    assert res.status_code == 200
    names = {g["name"] for g in res.json()["groups"]}
    assert tag in names
    # The old fixture groups must be gone.
    assert "All Workstations" not in names


# ---------------------------------------------------------------------------
# Containment gate — the actual security regression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_isolate_device_requires_authentication(client):
    """Previously this endpoint had no auth at all."""
    res = await client.post("/api/fleet/actions/isolate-device",
                            json={"device_id": "1", "reason": "test"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_isolate_device_stages_for_approval_and_does_not_execute(client):
    """
    The regression: this used to return isolation_active=true without an
    approval request. It must now stage through the same gate
    /api/response/isolate-host uses and report that nothing happened yet.
    """
    from database import get_db_manager
    await _seed_scope()
    headers = await _root_admin_headers(client)
    device_id = _seed_device(ip="203.0.113.82", hostname="fleet-isolate-host")

    res = await client.post("/api/fleet/actions/isolate-device",
                            json={"device_id": str(device_id), "reason": "suspected beaconing"},
                            headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["status"] == "staged"
    assert body["isolation_active"] is False
    approval_id = body["approval_request_id"]

    # A real, pending approval row must exist -- staged means staged.
    approval = get_db_manager().get_approval_request(approval_id)
    assert approval is not None
    assert approval["action_type"] == "isolate_host_staged"
    assert approval["status"] == "pending"
    # Same action_type as response.py's path, so the already-hardened
    # enforce endpoint can act on it. Target is the IP, not the hostname,
    # so it is checkable against the CIDR-based authorized scope.
    assert approval["target"] == "203.0.113.82"


@pytest.mark.asyncio
async def test_isolate_device_outside_authorized_scope_is_refused(client):
    """
    Scope is defined in CIDRs, so the staged target must be the device's
    IP -- targeting its hostname instead would put the request outside
    what tools/authorization.py can evaluate, silently skipping the scope
    check for any host that happens to have a hostname.
    """
    await _seed_scope()
    headers = await _root_admin_headers(client)
    # 198.51.100.0/24 (TEST-NET-2) is deliberately not in the seeded scope.
    device_id = _seed_device(ip="198.51.100.5", hostname="out-of-scope-host")

    res = await client.post("/api/fleet/actions/isolate-device",
                            json={"device_id": str(device_id), "reason": "should be refused"},
                            headers=headers)
    assert res.status_code == 403
    assert "scope" in res.text.lower()


@pytest.mark.asyncio
async def test_isolate_unknown_device_404s(client):
    headers = await _root_admin_headers(client)
    res = await client.post("/api/fleet/actions/isolate-device",
                            json={"device_id": "99999999", "reason": "test"},
                            headers=headers)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Agent-dependent actions — honest rather than fake success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_actions_report_not_configured_instead_of_fake_success(client):
    """
    These used to answer {"status": "executing", ...} with invented
    progress counters for operations this platform cannot perform.
    """
    headers = await _root_admin_headers(client)
    res = await client.post("/api/fleet/actions/deploy-patch?patch_id=KB123",
                            json=["1", "2"], headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "not_configured"
    assert body["executed"] is False


@pytest.mark.asyncio
async def test_agent_actions_require_authentication(client):
    res = await client.post("/api/fleet/actions/restart-devices", json=["1"])
    assert res.status_code == 401
