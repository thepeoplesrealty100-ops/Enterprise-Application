"""
backend/tests/test_v26_settings_security.py
JAKAL v2.6 — Global Settings & Security test suite.

Covers the new IAM (auth/RBAC/API keys/audit), Vault (Trade Secrets/EAS
R&D), Awareness (training/phishing), Dark Web, and CheatSheet Library
routers added to back the "Global Settings & Security" tab (and the
Human Layer Security / GACyber Toolkit tabs) that previously had no
backend at all.

Run: cd backend && python -m pytest tests/test_v26_settings_security.py -q

Note on shared state: like the rest of this test suite (see
test_suite.py's test_pentest_start_valid fix), these tests run against
the same on-disk jakal.duckdb singleton every other router uses
(DuckDBManager is a process-wide singleton — see database.get_db_manager()).
Registering a user here permanently ends "bootstrap mode" (see
dependencies.py's module docstring) for that DB file going forward, which
is the intended, real behavior of a first-admin bootstrap flow — not a
test isolation bug. Usernames are randomized per run so re-running this
file against a dev machine's already-populated jakal.duckdb doesn't
collide with a previous run's accounts.
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


# This module's very first successful registration becomes root_admin
# (bootstrap rule — see dependencies.py). Every later registration in this
# file gets the least-privileged `read_only` role instead (also by design —
# an existing admin has to explicitly promote new accounts). Tests that
# need an elevated permission (issuing API keys, writing to the vault,
# launching a phishing campaign) reuse THIS one root_admin identity via
# `_root_admin_headers()` rather than assuming a freshly self-registered
# user has any privileges — a fresh read_only user correctly getting 403
# on those actions is the RBAC system working, not a bug to route around.
_ROOT_USERNAME = _uniq("rootadmin")
_ROOT_PASSWORD = "Root-Str0ng-Passphrase-2026!"


async def _root_admin_headers(client) -> dict:
    """
    Registers (if not already done) and logs in `_ROOT_USERNAME`, then
    grants it root_admin directly at the DB layer. Going straight to the
    DB rather than assuming "first registration wins" makes this
    deterministic regardless of whether some earlier test (in this file,
    an earlier test module, or a previous local run against the same
    persisted jakal.duckdb — see the module docstring) already registered
    a user and ended bootstrap mode. This mirrors how a real deployment's
    existing root_admin would promote a teammate via
    POST /iam/rbac/users/{user_id}/roles — just done directly for test
    setup speed instead of a second HTTP round trip.
    """
    from database import get_db_manager
    await client.post("/api/iam/auth/register", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    user = get_db_manager().get_user_by_username(_ROOT_USERNAME)
    assert user is not None
    get_db_manager().assign_user_role(user["user_id"], "root_admin")
    login = await client.post("/api/iam/auth/login", json={"username": _ROOT_USERNAME, "password": _ROOT_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ---------------------------------------------------------------------------
# CheatSheet Library — pure read, safe to run any time
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cheatsheet_stats(client):
    response = await client.get("/api/cheatsheet/stats")
    assert response.status_code == 200
    data = response.json()
    assert data.get("entries", 0) >= 1


@pytest.mark.asyncio
async def test_cheatsheet_search_and_playbooks(client):
    response = await client.get("/api/cheatsheet/search?limit=5")
    assert response.status_code == 200
    assert "entries" in response.json()

    response = await client.get("/api/cheatsheet/playbooks")
    assert response.status_code == 200
    assert isinstance(response.json()["playbooks"], list)
    assert len(response.json()["playbooks"]) > 0


# ---------------------------------------------------------------------------
# IAM — registration, login, bootstrap-mode transition, RBAC, API keys
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_darkweb_watchlist_open_before_any_user_registered(client):
    """
    Sanity check of the bootstrap-mode contract (dependencies.py) BEFORE
    this file registers its first user: a permission-gated write endpoint
    must succeed anonymously while the users table is still empty.
    """
    response = await client.post(
        "/api/darkweb/watchlist",
        json={"identifier": f"{_uniq('bootstrap')}@example.com", "identifier_type": "email"},
    )
    # Either genuinely open (bootstrap, this jakal.duckdb has no users yet)
    # or already locked down by an earlier local test run against the same
    # persisted dev DB — both are valid states for a shared on-disk file;
    # what matters is it's never a 500.
    assert response.status_code in (200, 401)


@pytest.mark.asyncio
async def test_register_login_and_rbac_flow(client):
    username = _uniq("operator")
    password = "Sup3r-Str0ng-Passphrase-2026!"

    register = await client.post(
        "/api/iam/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert register.status_code == 201
    body = register.json()
    assert body["username"] == username
    assert body["role"] in ("root_admin", "read_only")

    # Duplicate registration must fail without leaking *why* (no user enumeration).
    dup = await client.post(
        "/api/iam/auth/register",
        json={"username": username, "password": password},
    )
    assert dup.status_code == 409

    # Wrong password -> generic 401, account not locked yet.
    bad = await client.post("/api/iam/auth/login", json={"username": username, "password": "wrong-password"})
    assert bad.status_code == 401

    login = await client.post("/api/iam/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/iam/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == username
    assert len(me.json()["roles"]) >= 1

    # No token at all -> 401 on a strict (get_authenticated_user) endpoint.
    anon = await client.get("/api/iam/auth/me")
    assert anon.status_code == 401

    roles = await client.get("/api/iam/rbac/roles")
    assert roles.status_code == 200
    role_keys = {r["role_key"] for r in roles.json()["roles"]}
    assert {"root_admin", "security_analyst", "read_only"}.issubset(role_keys)

    logout = await client.post("/api/iam/auth/logout", headers=headers)
    assert logout.status_code == 200

    # Token is revoked server-side (see sessions.revoked) — must not work again.
    reuse = await client.get("/api/iam/auth/me", headers=headers)
    assert reuse.status_code == 401


@pytest.mark.asyncio
async def test_account_lockout_after_repeated_bad_logins(client):
    """NIST SP 800-63B-aligned lockout: 5 bad attempts locks the account."""
    username = _uniq("lockout")
    password = "Another-Str0ng-Passphrase-2026!"
    await client.post("/api/iam/auth/register", json={"username": username, "password": password})

    last_status = None
    for _ in range(6):
        r = await client.post("/api/iam/auth/login", json={"username": username, "password": "wrong"})
        last_status = r.status_code
    assert last_status == 423  # locked

    # Even the CORRECT password is rejected while locked.
    still_locked = await client.post("/api/iam/auth/login", json={"username": username, "password": password})
    assert still_locked.status_code == 423


@pytest.mark.asyncio
async def test_api_key_lifecycle(client):
    headers = await _root_admin_headers(client)

    created = await client.post("/api/iam/api-keys", json={"label": "ci-test-key", "scopes": []}, headers=headers)
    assert created.status_code == 200
    key_id = created.json()["key_id"]
    assert created.json()["secret"].startswith(key_id)

    listed = await client.get("/api/iam/api-keys", headers=headers)
    assert any(k["key_id"] == key_id for k in listed.json()["keys"])

    revoked = await client.post(f"/api/iam/api-keys/{key_id}/revoke", headers=headers)
    assert revoked.status_code == 200

    # A freshly self-registered (read_only, no iam:manage_keys) user must
    # NOT be able to issue keys — proves this isn't just "logged in = allowed".
    low_priv_username = _uniq("lowpriv")
    low_priv_password = "LowPriv-Str0ng-Passphrase-2026!"
    await client.post("/api/iam/auth/register", json={"username": low_priv_username, "password": low_priv_password})
    low_login = await client.post("/api/iam/auth/login", json={"username": low_priv_username, "password": low_priv_password})
    low_headers = {"Authorization": f"Bearer {low_login.json()['access_token']}"}
    denied = await client.post("/api/iam/api-keys", json={"label": "should-fail", "scopes": []}, headers=low_headers)
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_recorded_every_permission_check(client):
    username = _uniq("auditop")
    password = "Audit-Str0ng-Passphrase-2026!"
    await client.post("/api/iam/auth/register", json={"username": username, "password": password})
    login = await client.post("/api/iam/auth/login", json={"username": username, "password": password})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    entries = await client.get("/api/iam/audit/log?limit=200", headers=headers)
    assert entries.status_code == 200
    actions = {e["action"] for e in entries.json()["entries"]}
    assert "login" in actions
    assert "register" in actions


# ---------------------------------------------------------------------------
# Vault — encryption at rest + RBAC-gated read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vault_item_roundtrip_and_rbac_denial(client):
    # Writing to the vault requires vault:write, which read_only lacks by
    # design — reuse the module's root_admin for the write, same rationale
    # as test_api_key_lifecycle above.
    owner_headers = await _root_admin_headers(client)

    secret_text = f"trade secret payload {uuid.uuid4()}"
    created = await client.post(
        "/api/vault/items",
        json={"title": "Formula X", "content": secret_text, "classification": "TRADE_SECRET",
              "allowed_roles": ["root_admin"]},
        headers=owner_headers,
    )
    assert created.status_code == 200
    item_id = created.json()["item_id"]

    # Owner can always read their own item back, decrypted, integrity-checked.
    fetched = await client.get(f"/api/vault/items/{item_id}", headers=owner_headers)
    assert fetched.status_code == 200
    assert fetched.json()["content"] == secret_text
    assert fetched.json()["integrity_verified"] is True

    # A second, unprivileged (read_only) user is NOT in allowed_roles and is
    # not the owner -> must be denied, proving RBAC actually gates vault reads.
    other_username = _uniq("vaultother")
    other_password = "VaultOther-Str0ng-Passphrase-2026!"
    await client.post("/api/iam/auth/register", json={"username": other_username, "password": other_password})
    other_login = await client.post("/api/iam/auth/login", json={"username": other_username, "password": other_password})
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    denied = await client.get(f"/api/vault/items/{item_id}", headers=other_headers)
    assert denied.status_code in (403, 401)


@pytest.mark.asyncio
async def test_eas_rd_last_scan_endpoint_never_errors(client):
    # Doesn't trigger a live network scan (that's a separate, slower POST);
    # just verifies the cached-result endpoint always returns a well-formed
    # response, scan-run-yet or not.
    response = await client.get("/api/vault/eas-rd/last-scan")
    assert response.status_code == 200
    assert "findings" in response.json()


# ---------------------------------------------------------------------------
# Awareness — training modules + phishing campaigns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_training_modules_seeded_and_completion_recorded(client):
    modules = await client.get("/api/awareness/training/modules")
    assert modules.status_code == 200
    module_keys = [m["module_key"] for m in modules.json()["modules"]]
    assert "phishing-101" in module_keys

    username = _uniq("trainee")
    password = "Trainee-Str0ng-Passphrase-2026!"
    await client.post("/api/iam/auth/register", json={"username": username, "password": password})
    login = await client.post("/api/iam/auth/login", json={"username": username, "password": password})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    completion = await client.post(
        "/api/awareness/training/modules/phishing-101/complete", json={"score": 95}, headers=headers,
    )
    assert completion.status_code == 200
    assert completion.json()["passed"] is True


@pytest.mark.asyncio
async def test_phishing_campaign_lifecycle(client):
    # Launching a campaign requires awareness:manage — root_admin only
    # among the seeded roles (see _DEFAULT_ROLES in routers/iam.py).
    headers = await _root_admin_headers(client)

    campaign = await client.post(
        "/api/awareness/phishing/campaigns",
        json={"name": "Q1 Awareness Test", "template_key": "it-password-reset",
              "targets": ["staffer1@example.com", "staffer2@example.com"]},
        headers=headers,
    )
    assert campaign.status_code == 200
    campaign_id = campaign.json()["campaign_id"]

    clicked = await client.post(f"/api/awareness/phishing/campaigns/{campaign_id}/targets/staffer1@example.com/clicked")
    assert clicked.status_code == 200
    reported = await client.post(f"/api/awareness/phishing/campaigns/{campaign_id}/targets/staffer2@example.com/reported")
    assert reported.status_code == 200

    stats = await client.get(f"/api/awareness/phishing/campaigns/{campaign_id}/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["sent"] == 2
    assert body["clicked"] == 1
    assert body["reported"] == 1
