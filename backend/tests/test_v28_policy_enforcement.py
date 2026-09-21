"""
backend/tests/test_v28_policy_enforcement.py
JAKAL v2.8 — Resonance Wave Automation policy + Detection & Response
enforcement (Docker sandbox isolation + signed webhook connector).

Run: cd backend && python -m pytest tests/test_v28_policy_enforcement.py -q

Two of these tests are REAL integration tests, not mocks:
  - test_docker_sandbox_isolation_real_network_disconnect actually creates
    a Docker network + container and asserts the container is genuinely
    disconnected afterward (skips cleanly if no Docker daemon is reachable
    or the tiny local test image can't be built -- see _ensure_test_image).
  - test_webhook_connector_delivers_verifiable_signature runs a real
    local HTTP server in a background thread and asserts the connector's
    HMAC signature verifies against security_agents/edr_connector.py's
    own reference verify_webhook_signature() -- proving the sender and
    the documented receiver-side implementation actually agree, not just
    that "some string that looks like a signature" was sent.
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
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


_ROOT_USERNAME = _uniq("v28root")
_ROOT_PASSWORD = "V28Root-Str0ng-Passphrase-2026!"


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
    db.add_scope("v28-test", target_cidr, now - timedelta(days=1), now + timedelta(days=30))
    db.add_insurance_policy(f"V28-POL-{now.timestamp()}", "Test Underwriter", 1_000_000, now + timedelta(days=365))


# ---------------------------------------------------------------------------
# Resonance policy — real CRUD + permission gating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_seeded_and_listable(client):
    response = await client.get("/api/resonance/automation-settings")
    assert response.status_code == 200
    keys = {p["policy_key"] for p in response.json()["policy"]}
    assert {"response_auto_stage_threshold", "trade_secret_isolation_enforced",
            "auto_approve_low_risk_actions", "sandbox_max_lifetime_hours"}.issubset(keys)


@pytest.mark.asyncio
async def test_policy_write_requires_permission_and_type_checks(client):
    headers = await _root_admin_headers(client)

    anon = await client.post("/api/resonance/automation-settings/sandbox_max_lifetime_hours", json={"value": 12})
    assert anon.status_code == 401

    wrong_type = await client.post("/api/resonance/automation-settings/sandbox_max_lifetime_hours",
                                    json={"value": "not-a-number"}, headers=headers)
    assert wrong_type.status_code == 422

    unknown = await client.post("/api/resonance/automation-settings/does-not-exist", json={"value": 1}, headers=headers)
    assert unknown.status_code == 404

    ok = await client.post("/api/resonance/automation-settings/sandbox_max_lifetime_hours", json={"value": 6}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["value"] == 6

    listed = await client.get("/api/resonance/automation-settings")
    row = next(p for p in listed.json()["policy"] if p["policy_key"] == "sandbox_max_lifetime_hours")
    assert row["value"] == 6
    assert row["updated_by"] == _ROOT_USERNAME


@pytest.mark.asyncio
async def test_stale_sandboxes_uses_policy_threshold(client):
    headers = await _root_admin_headers(client)
    await client.post("/api/resonance/automation-settings/sandbox_max_lifetime_hours", json={"value": 0}, headers=headers)
    response = await client.get("/api/resonance/automation-settings/stale-sandboxes")
    assert response.status_code == 200
    assert response.json()["max_lifetime_hours"] == 0
    # Restore a sane default so later tests in this module aren't affected.
    await client.post("/api/resonance/automation-settings/sandbox_max_lifetime_hours", json={"value": 24}, headers=headers)


# ---------------------------------------------------------------------------
# Enforcement wiring — trade_secret_isolation_enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trade_secret_isolation_policy_rejects_empty_roles_when_on(client):
    headers = await _root_admin_headers(client)
    await client.post("/api/resonance/automation-settings/trade_secret_isolation_enforced", json={"value": True}, headers=headers)

    denied = await client.post("/api/vault/items",
                                json={"title": "Unscoped", "content": "x", "allowed_roles": []}, headers=headers)
    assert denied.status_code == 422

    await client.post("/api/resonance/automation-settings/trade_secret_isolation_enforced", json={"value": False}, headers=headers)
    allowed = await client.post("/api/vault/items",
                                 json={"title": "Unscoped-ok", "content": "x", "allowed_roles": []}, headers=headers)
    assert allowed.status_code == 200
    # Restore the safer default.
    await client.post("/api/resonance/automation-settings/trade_secret_isolation_enforced", json={"value": True}, headers=headers)


# ---------------------------------------------------------------------------
# Enforcement wiring — response_auto_stage_threshold as the triage default
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_triage_uses_policy_threshold_when_not_overridden(client):
    headers = await _root_admin_headers(client)
    await client.post("/api/resonance/automation-settings/response_auto_stage_threshold", json={"value": 0.3}, headers=headers)

    # A moderate finding (severity ~0.55, verified via threat_scoring
    # directly) that would NOT auto-stage at the old hardcoded 0.8 default,
    # but SHOULD once the org policy is lowered to 0.3. "phishing" as the
    # threat_category also guarantees a playbook match (phishing_quarantine)
    # -- auto-staging requires both severity >= threshold AND a
    # recommendation, by design (see _recommend_playbooks in response.py).
    response = await client.post("/api/response/triage", json={
        "finding_summary": "phishing email led to credential harvesting, user reported suspicious activity",
        "threat_category": "phishing",
        "target": "203.0.113.50",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["auto_stage_threshold_used"] == 0.3
    assert body["severity"] >= 0.3
    assert len(body["recommended_playbooks"]) > 0
    assert body["auto_staged_approval_request_id"] is not None

    await client.post("/api/resonance/automation-settings/response_auto_stage_threshold", json={"value": 0.8}, headers=headers)


# ---------------------------------------------------------------------------
# Enforcement wiring — auto_approve_low_risk_actions for the script catalog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_approve_low_risk_scripts_when_policy_on(client):
    headers = await _root_admin_headers(client)
    await _seed_scope()
    await client.post("/api/resonance/automation-settings/auto_approve_low_risk_actions", json={"value": True}, headers=headers)

    listing = await client.get("/api/cheatsheet/scripts?risk_level=LOW")
    script_id = listing.json()["scripts"][0]["id"]
    staged = await client.post(f"/api/cheatsheet/scripts/{script_id}/stage",
                                json={"target": "203.0.113.60"}, headers=headers)
    assert staged.status_code == 200
    assert staged.json()["status"] == "approved"

    approval = await client.get(f"/api/approval/{staged.json()['approval_request_id']}")
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"
    assert approval.json()["decided_by"] == "system:auto-approve-policy"

    await client.post("/api/resonance/automation-settings/auto_approve_low_risk_actions", json={"value": False}, headers=headers)

    # With the policy off again, staging the SAME risk class must go back
    # to waiting on a human.
    listing2 = await client.get("/api/cheatsheet/scripts?risk_level=LOW")
    script_id2 = listing2.json()["scripts"][1]["id"]
    staged2 = await client.post(f"/api/cheatsheet/scripts/{script_id2}/stage",
                                 json={"target": "203.0.113.61"}, headers=headers)
    assert staged2.status_code == 200
    assert staged2.json()["status"] == "staged"


# ---------------------------------------------------------------------------
# Webhook enforcement connector — REAL local HTTP server, REAL signature verify
# ---------------------------------------------------------------------------

class _CapturingWebhookHandler(http.server.BaseHTTPRequestHandler):
    received = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _CapturingWebhookHandler.received = {
            "body": body,
            "timestamp": self.headers.get("X-JAKAL-Timestamp"),
            "nonce": self.headers.get("X-JAKAL-Nonce"),
            "signature": self.headers.get("X-JAKAL-Signature"),
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "received"}')

    def log_message(self, *args):
        pass  # keep test output quiet


@pytest.fixture
def local_webhook_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _CapturingWebhookHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/hook"
    server.shutdown()
    thread.join(timeout=5)


def test_webhook_connector_delivers_verifiable_signature(local_webhook_server, monkeypatch):
    from security_agents.edr_connector import WebhookEnforcementConnector, verify_webhook_signature

    secret = "test-shared-secret-do-not-use-in-prod"
    connector = WebhookEnforcementConnector(url=local_webhook_server, secret=secret)
    assert connector.configured

    result = connector.enforce("isolate_host_staged", "198.51.100.77", {"reason": "test"}, "tester")
    assert result["status"] == "enforced", result

    received = _CapturingWebhookHandler.received
    assert received, "webhook handler never received a request"
    assert verify_webhook_signature(
        secret, received["timestamp"], received["nonce"], received["body"], received["signature"],
    ) is True
    # Wrong secret must fail -- proves this isn't a signature-shaped no-op.
    assert verify_webhook_signature(
        "wrong-secret", received["timestamp"], received["nonce"], received["body"], received["signature"],
    ) is False
    body = json.loads(received["body"])
    assert body["target"] == "198.51.100.77"
    assert body["action_type"] == "isolate_host_staged"


def test_webhook_connector_not_configured_is_honest():
    from security_agents.edr_connector import WebhookEnforcementConnector
    connector = WebhookEnforcementConnector(url="", secret="")
    assert connector.configured is False
    result = connector.enforce("isolate_host_staged", "198.51.100.77", {}, "tester")
    assert result["status"] == "not_configured"


# ---------------------------------------------------------------------------
# Docker sandbox isolation connector — REAL container + network, real daemon
# ---------------------------------------------------------------------------

def _ensure_test_image() -> bool:
    """
    Builds a ~2MB from-scratch test image out of the OS's own busybox-static
    binary if present -- no network pull required (Docker Hub is not
    reachable from this sandbox's egress policy, apt's Ubuntu archive is).
    Returns False (skip the test) if Docker isn't reachable or no local
    busybox binary can be found, rather than trying to fetch one.
    """
    try:
        import docker
        client = docker.from_env()
        client.ping()
    except Exception:
        return False

    try:
        client.images.get("jakal-test-minimal:latest")
        return True
    except Exception:
        pass

    busybox_path = shutil.which("busybox")
    if not busybox_path:
        return False

    build_dir = Path("/tmp/jakal-test-image-pytest")
    build_dir.mkdir(exist_ok=True)
    shutil.copy(busybox_path, build_dir / "busybox")
    (build_dir / "Dockerfile").write_text(
        'FROM scratch\nCOPY busybox /busybox\nENTRYPOINT ["/busybox", "sleep", "infinity"]\n'
    )
    result = subprocess.run(
        ["docker", "build", "-t", "jakal-test-minimal:latest", str(build_dir)],
        capture_output=True, text=True, timeout=60,
    )
    return result.returncode == 0


@pytest.mark.skipif(not _ensure_test_image(), reason="Docker daemon or a buildable local test image is not available in this environment")
def test_docker_sandbox_isolation_real_network_disconnect():
    """
    Creates a real Docker bridge network and a real jakal.sandbox-labeled
    container attached to it, calls DockerSandboxIsolationConnector.isolate()
    for real, and asserts the container has zero networks afterward --
    genuine MITRE D3FEND D3-NI Network Isolation, not a mock.
    """
    import docker
    from security_agents.vm_orchestrator import VMOrchestrator
    from security_agents.edr_connector import DockerSandboxIsolationConnector

    client = docker.from_env()
    net_name = f"jakal-pytest-net-{uuid.uuid4().hex[:8]}"
    container_name = f"jakal-sandbox-pytest-{uuid.uuid4().hex[:8]}"
    network = None
    container = None
    try:
        network = client.networks.create(net_name, driver="bridge")
        container = client.containers.run(
            "jakal-test-minimal:latest", name=container_name, detach=True, network=net_name,
            labels={"jakal.sandbox": "true", "jakal.name": "pytest"},
        )
        container.reload()
        assert net_name in container.attrs["NetworkSettings"]["Networks"]

        vm = VMOrchestrator(db_manager=None)
        connector = DockerSandboxIsolationConnector(vm)
        result = connector.isolate(container_name, "pytest-operator")

        assert result["status"] == "enforced", result
        assert net_name in result["detail"]["networks_disconnected"]

        container.reload()
        assert container.attrs["NetworkSettings"]["Networks"] == {}
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        if network is not None:
            try:
                network.remove()
            except Exception:
                pass


@pytest.mark.asyncio
async def test_enforce_endpoint_end_to_end_via_webhook(client, local_webhook_server, monkeypatch):
    """
    Full API-level path: stage isolate-host -> approve -> enforce, with
    EDR_WEBHOOK_URL pointed at the real local test server for this one
    test (monkeypatch'd env var, read fresh by WebhookEnforcementConnector
    per-call rather than cached at import time). Asserts the enforcement
    actually reached the server AND the remediation_actions row reflects it.
    """
    monkeypatch.setenv("EDR_WEBHOOK_URL", local_webhook_server)
    monkeypatch.setenv("EDR_WEBHOOK_SECRET", "e2e-test-secret")

    headers = await _root_admin_headers(client)
    await _seed_scope("203.0.113.0/24")
    target = "203.0.113.99"  # not a known sandbox container_name -> webhook path

    staged = await client.post("/api/response/isolate-host",
                                json={"target": target, "reason": "e2e enforcement test"}, headers=headers)
    assert staged.status_code == 200
    approval_request_id = staged.json()["approval_request_id"]

    # Not enforceable before approval.
    too_early = await client.post(f"/api/response/actions/{approval_request_id}/enforce", headers=headers)
    assert too_early.status_code == 403

    # v3.0 Phase 5: isolate-host is HIGH risk -> gets a real Maya-Vigesimal
    # interlock now, same as an offensive HIGH/CRITICAL payload. Consume it
    # before approving, same as a real operator would.
    maya = staged.json()["maya_challenge"]
    assert maya is not None
    verify = await client.post("/api/v3/auth/maya/verify", json={
        "session_id": maya["session_id"], "response_token": maya["challenge_token"],
        "operator_id": _ROOT_USERNAME,
    })
    assert verify.status_code == 200

    approve = await client.post(f"/api/approval/{approval_request_id}/approve",
                                 json={"operator_id": _ROOT_USERNAME}, headers=headers)
    assert approve.status_code == 200

    enforced = await client.post(f"/api/response/actions/{approval_request_id}/enforce", headers=headers)
    assert enforced.status_code == 200
    body = enforced.json()
    assert body["status"] == "enforced"
    assert body["connector"] == "webhook"
    assert body["target"] == target

    assert _CapturingWebhookHandler.received.get("body") is not None
    delivered = json.loads(_CapturingWebhookHandler.received["body"])
    assert delivered["target"] == target
    assert delivered["action_type"] == "isolate_host_staged"

    actions = await client.get(f"/api/response/actions?limit=50")
    # isolate_host's own remediation_actions row has its own action_id
    # (see _record_action in response.py) -- it's linked to the approval
    # via the approval_request_id column, not equal to it.
    matching = [a for a in actions.json()["actions"] if a["approval_request_id"] == approval_request_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "enforced"


@pytest.mark.skipif(not _ensure_test_image(), reason="Docker daemon or a buildable local test image is not available in this environment")
def test_docker_sandbox_isolation_refuses_non_jakal_container():
    """The ownership check (jakal.sandbox label) must reject a container
    this platform didn't create -- proven against a real container, not
    an assumption about the code path."""
    import docker
    from security_agents.vm_orchestrator import VMOrchestrator
    from security_agents.edr_connector import DockerSandboxIsolationConnector

    client = docker.from_env()
    container_name = f"not-jakal-{uuid.uuid4().hex[:8]}"
    container = client.containers.run(
        "jakal-test-minimal:latest", name=container_name, detach=True,
    )  # deliberately no jakal.sandbox label
    try:
        vm = VMOrchestrator(db_manager=None)
        connector = DockerSandboxIsolationConnector(vm)
        result = connector.isolate(container_name, "pytest-operator")
        assert result["status"] == "error"
        assert "non-JAKAL-managed" in result["detail"]["error"]
    finally:
        container.remove(force=True)
