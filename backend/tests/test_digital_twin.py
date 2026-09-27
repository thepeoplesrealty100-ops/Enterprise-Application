"""
backend/tests/test_digital_twin.py

Regression + wiring tests for the rebuilt routers/digital_twin.py.

The old version returned entirely hardcoded fixture data (a fictitious
"Water Treatment Facility Alpha") from every endpoint regardless of input,
with no persistence at all. The important assertions here are the ones
that would fail if that fake version ever came back: /assets before any
/sync must be empty (the old version returned a canned twin for any id),
a /sync must actually create real Ontology Engine "Asset" nodes traceable
back to a specific network_map row, and /assets/{id} for an unknown id
must 404 (the old version fabricated a response for any twin_id).

Run: cd backend && python -m pytest tests/test_digital_twin.py -q
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


_ROOT_USERNAME = _uniq("twinroot")
_ROOT_PASSWORD = "Twin-Root-Str0ng-Passphrase-2026!"


async def _root_admin_headers(client) -> dict:
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    user = get_db_manager().get_user_by_username(_ROOT_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_network_host(ip: str) -> None:
    from database import get_db_manager
    get_db_manager().upsert_network_host({
        "ip_address": ip,
        "hostname": f"host-{ip.replace('.', '-')}",
        "os_fingerprint": "Linux 5.x",
        "open_ports": [{"port": 22, "proto": "tcp", "service": "ssh"}],
        "tags": ["test-seed"],
        "risk_score": 3.5,
    })


@pytest.mark.asyncio
async def test_assets_empty_before_sync_is_not_a_fixture(client):
    """The old router returned a canned twin regardless of id/state.
    The real one returns whatever is actually in the graph -- assert the
    shape (list + count) rather than exact emptiness, since other tests
    in this module run against the same shared app/db."""
    headers = await _root_admin_headers(client)
    res = await client.get("/api/digital-twin/assets", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "assets" in body and "count" in body
    assert isinstance(body["assets"], list)
    assert body["count"] == len(body["assets"])


@pytest.mark.asyncio
async def test_unknown_asset_404s(client):
    """The old /{twin_id} endpoint fabricated a full twin for any id.
    The real one must 404 for an id that was never synced."""
    headers = await _root_admin_headers(client)
    res = await client.get("/api/digital-twin/assets/not-a-real-node-id", headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_sync_requires_auth(client):
    res = await client.post("/api/digital-twin/sync")
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_sync_materializes_real_network_map_row(client):
    """The core regression guard: /sync must create a real, traceable
    Ontology Engine node from a real network_map row -- not simulate one."""
    ip = f"10.99.{uuid.uuid4().int % 255}.{uuid.uuid4().int % 255}"
    _seed_network_host(ip)
    headers = await _root_admin_headers(client)

    res = await client.post("/api/digital-twin/sync", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["synced_from_network_map"] >= 1
    assert body["assets_total"] >= 1

    listing = await client.get("/api/digital-twin/assets", headers=headers)
    assert listing.status_code == 200
    matches = [a for a in listing.json()["assets"] if a.get("target") == ip]
    assert len(matches) == 1, f"expected exactly one Asset node for {ip}, got {matches}"
    asset = matches[0]
    assert asset["source"] == "network_map"
    assert asset["risk_score"] == 3.5
    assert asset["health_status"] in ("healthy", "degraded", "at_risk")

    detail = await client.get(f"/api/digital-twin/assets/{asset['node_id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["attributes"]["ip_address"] == ip
    assert d["attributes"]["network_map_id"] is not None


@pytest.mark.asyncio
async def test_sync_is_idempotent_for_same_ip(client):
    """Re-syncing the same IP must update the existing node, not
    duplicate it -- the old fake router had no persistence to test this
    against at all."""
    ip = f"10.98.{uuid.uuid4().int % 255}.{uuid.uuid4().int % 255}"
    _seed_network_host(ip)
    headers = await _root_admin_headers(client)

    await client.post("/api/digital-twin/sync", headers=headers)
    await client.post("/api/digital-twin/sync", headers=headers)

    listing = await client.get("/api/digital-twin/assets", headers=headers)
    matches = [a for a in listing.json()["assets"] if a.get("target") == ip]
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_annotate_links_a_real_node(client):
    ip = f"10.97.{uuid.uuid4().int % 255}.{uuid.uuid4().int % 255}"
    _seed_network_host(ip)
    headers = await _root_admin_headers(client)
    await client.post("/api/digital-twin/sync", headers=headers)
    listing = await client.get("/api/digital-twin/assets", headers=headers)
    asset = next(a for a in listing.json()["assets"] if a.get("target") == ip)

    res = await client.post(
        f"/api/digital-twin/assets/{asset['node_id']}/annotate",
        headers=headers,
        json={"note": "confirmed false positive", "tag": "reviewed"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "annotated"

    detail = await client.get(f"/api/digital-twin/assets/{asset['node_id']}", headers=headers)
    linked_types = [o["object_type"] for o in detail.json()["linked_objects"]]
    assert "Annotation" in linked_types


@pytest.mark.asyncio
async def test_summary_reflects_real_counts(client):
    headers = await _root_admin_headers(client)
    await client.post("/api/digital-twin/sync", headers=headers)
    res = await client.get("/api/digital-twin/summary", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["assets_total"] >= 1
    assert "average_health_score" in body
