"""
backend/security_agents/edr_connector.py
============================================
Enforcement connectors for staged Detection & Response containment
decisions (routers/response.py) — JAKAL v2.8.

Context: v2.7 shipped host isolation/quarantine as a staged, PQC-signed,
human-approved *decision* (an approval_requests row), explicitly NOT
auto-enforced, because this platform doesn't control a customer's real
network. v2.8 closes that gap the only two honest ways available to a
platform in this position:

1. **Real enforcement for infrastructure this platform actually owns** —
   a JAKAL-provisioned sandbox container (security_agents/vm_orchestrator.py).
   `DockerSandboxIsolationConnector` genuinely disconnects the container
   from every Docker network it's attached to via the same `docker` SDK
   client VMOrchestrator already uses. This is real network isolation
   (MITRE D3FEND D3-NI), not a simulation — verified in
   tests/test_v28_policy_enforcement.py by actually creating a bridge
   network, attaching a throwaway container, isolating it, and asserting
   the network list is empty afterward.

2. **A real, standard integration point for infrastructure this platform
   does NOT own** — `WebhookEnforcementConnector`. This is exactly how
   production SOAR platforms bridge to a customer's actual EDR/firewall:
   Cortex XSOAR's CrowdStrike playbooks and Splunk SOAR's connectors both
   work by calling the vendor's own isolation API with the vendor's own
   credentials, which only the customer has — a third-party tool cannot
   call CrowdStrike's or SentinelOne's device-isolation API without them.
   So the connector fires a signed webhook this deployment's operator
   points at whatever bridges to their real EDR/firewall (their own
   Falcon/Singularity API wrapper, a Shuffle/TheHive/Cortex workflow, a
   firewall's own webhook-triggered ACL update, etc.) — the same shape
   every one of those tools already expects to receive automation calls
   in. See docs/v2.8-automation-policy-and-enforcement.md for the
   CrowdStrike/SentinelOne/Splunk SOAR research this is grounded in.

   Signing follows the HMAC webhook best-practice pattern (timestamp +
   nonce for replay protection, sign the raw body, constant-time compare
   on the receiving end): headers X-JAKAL-Timestamp, X-JAKAL-Nonce,
   X-JAKAL-Signature (hex HMAC-SHA256 over "{timestamp}.{nonce}.{body}").
   `verify_webhook_signature()` below is the reference receiver-side
   implementation — copy it into whatever service EDR_WEBHOOK_URL points at.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT_SECONDS = 10
_REPLAY_WINDOW_SECONDS = 300  # 5 minutes, matching common webhook-security guidance


class EnforcementResult(dict):
    """Just a Dict[str, Any] with a documented shape:
    {status: 'enforced'|'not_configured'|'error', connector: str, detail: {...}}"""


def sign_webhook_payload(secret: str, timestamp: str, nonce: str, raw_body: bytes) -> str:
    message = f"{timestamp}.{nonce}.".encode("utf-8") + raw_body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_webhook_signature(secret: str, timestamp: str, nonce: str, raw_body: bytes,
                              signature: str, now: Optional[float] = None) -> bool:
    """Reference implementation for whatever receives JAKAL's enforcement
    webhook. Rejects stale/replayed timestamps and uses a constant-time
    comparison — copy this pattern, don't compare signatures with `==`."""
    now = now if now is not None else time.time()
    try:
        ts = float(timestamp)
    except ValueError:
        return False
    if abs(now - ts) > _REPLAY_WINDOW_SECONDS:
        return False
    expected = sign_webhook_payload(secret, timestamp, nonce, raw_body)
    return hmac.compare_digest(expected, signature)


class DockerSandboxIsolationConnector:
    """
    Real network isolation for a container VMOrchestrator provisioned
    (jakal.sandbox label required — same ownership check
    VMOrchestrator.exec_in_sandbox already enforces, applied here too so
    this connector can never be pointed at a container this platform
    didn't create).
    """

    def __init__(self, vm_orchestrator):
        self._vm = vm_orchestrator

    def isolate(self, container_name: str, operator_id: str) -> EnforcementResult:
        if not self._vm.available:
            return EnforcementResult(status="error", connector="docker_sandbox_isolation",
                                      detail={"error": "docker daemon unavailable"})
        try:
            container = self._vm._client.containers.get(container_name)
        except Exception as e:
            return EnforcementResult(status="error", connector="docker_sandbox_isolation",
                                      detail={"error": f"container not found: {e}"})
        if "jakal.sandbox" not in (container.labels or {}):
            return EnforcementResult(status="error", connector="docker_sandbox_isolation",
                                      detail={"error": "refusing to isolate a non-JAKAL-managed container"})

        networks = list((container.attrs.get("NetworkSettings", {}).get("Networks", {}) or {}).keys())
        disconnected = []
        errors = []
        for net_name in networks:
            try:
                network = self._vm._client.networks.get(net_name)
                network.disconnect(container, force=True)
                disconnected.append(net_name)
            except Exception as e:
                errors.append({"network": net_name, "error": str(e)})

        status = "enforced" if disconnected and not errors else ("error" if errors else "not_configured")
        return EnforcementResult(
            status=status, connector="docker_sandbox_isolation",
            detail={"container_name": container_name, "networks_disconnected": disconnected,
                    "errors": errors, "operator_id": operator_id},
        )

    def reconnect(self, container_name: str, network_name: str = "bridge") -> EnforcementResult:
        """Recovery path — reconnect an isolated sandbox once an investigation clears it."""
        if not self._vm.available:
            return EnforcementResult(status="error", connector="docker_sandbox_isolation",
                                      detail={"error": "docker daemon unavailable"})
        try:
            container = self._vm._client.containers.get(container_name)
            network = self._vm._client.networks.get(network_name)
            network.connect(container)
        except Exception as e:
            return EnforcementResult(status="error", connector="docker_sandbox_isolation",
                                      detail={"error": str(e)})
        return EnforcementResult(status="enforced", connector="docker_sandbox_isolation",
                                  detail={"container_name": container_name, "reconnected_to": network_name})


class WebhookEnforcementConnector:
    """Signed outbound webhook — the real integration point for a
    customer's actual EDR/firewall/SOAR (see module docstring)."""

    def __init__(self, url: Optional[str] = None, secret: Optional[str] = None):
        self.url = url if url is not None else os.getenv("EDR_WEBHOOK_URL", "")
        self.secret = secret if secret is not None else os.getenv("EDR_WEBHOOK_SECRET", "")

    @property
    def configured(self) -> bool:
        return bool(self.url and self.secret)

    def enforce(self, action_type: str, target: str, detail: Dict[str, Any],
                operator_id: str) -> EnforcementResult:
        if not self.configured:
            return EnforcementResult(
                status="not_configured", connector="webhook",
                detail={"note": "Set EDR_WEBHOOK_URL and EDR_WEBHOOK_SECRET in backend/.env to "
                                 "enable real enforcement delivery to your EDR/firewall/SOAR."},
            )
        body = {
            "action_type": action_type, "target": target, "operator_id": operator_id,
            "detail": detail, "request_id": str(uuid.uuid4()),
        }
        raw_body = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        timestamp = str(time.time())
        nonce = uuid.uuid4().hex
        signature = sign_webhook_payload(self.secret, timestamp, nonce, raw_body)
        try:
            resp = requests.post(
                self.url, data=raw_body,
                headers={
                    "Content-Type": "application/json",
                    "X-JAKAL-Timestamp": timestamp,
                    "X-JAKAL-Nonce": nonce,
                    "X-JAKAL-Signature": signature,
                },
                timeout=_WEBHOOK_TIMEOUT_SECONDS,
            )
            ok = 200 <= resp.status_code < 300
            return EnforcementResult(
                status="enforced" if ok else "error", connector="webhook",
                detail={"http_status": resp.status_code, "response_snippet": resp.text[:500]},
            )
        except requests.RequestException as e:
            return EnforcementResult(status="error", connector="webhook", detail={"error": str(e)})


def enforce_containment(action_type: str, target: str, detail: Dict[str, Any], operator_id: str,
                         db=None, vm_orchestrator=None) -> EnforcementResult:
    """
    Dispatcher: if `target` names a live JAKAL sandbox container, isolate
    it for real via Docker. Otherwise it's an external target this
    platform doesn't own — deliver via the signed webhook connector (or
    report not_configured, honestly, if no webhook is set up).
    """
    is_sandbox = False
    if db is not None:
        try:
            row = db.conn.execute(
                "SELECT 1 FROM sandboxes WHERE container_name = ? AND status != 'destroyed'",
                (target,),
            ).fetchone()
            is_sandbox = bool(row)
        except Exception:
            is_sandbox = False

    if is_sandbox and vm_orchestrator is not None:
        connector = DockerSandboxIsolationConnector(vm_orchestrator)
        return connector.isolate(target, operator_id)

    webhook = WebhookEnforcementConnector()
    return webhook.enforce(action_type, target, detail, operator_id)
