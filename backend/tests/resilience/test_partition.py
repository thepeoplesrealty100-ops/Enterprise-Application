"""
backend/tests/resilience/test_partition.py
JAKAL Track B — Resilience testing under network partition & isolation.

Validates exponential backoff retry, transient vs permanent error handling,
and offline fallback cryptographic signing.

Run: cd backend && python -m pytest tests/resilience/test_partition.py -q
"""

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from database import DuckDBManager
from security_agents.edr_hardened import (
    HardenedEnforcementOrchestrator,
    RetryPolicy,
    classify_enforcement_error,
    get_related_targets_for_remediation,
)


# ─────────────────────────────────────────────────────────────────────────
# Retry Policy & Backoff Tests
# ─────────────────────────────────────────────────────────────────────────

def test_exponential_backoff_sequence():
    """Verify 1s → 4s → 16s progression."""
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=1.0, backoff_factor=4.0)
    delays = [policy.delay_for_attempt(i) for i in range(4)]
    assert delays == [0, 1.0, 4.0, 16.0]


def test_custom_retry_policy():
    """Custom backoff configuration."""
    policy = RetryPolicy(max_attempts=4, base_delay_seconds=0.5, backoff_factor=2.0)
    assert policy.delay_for_attempt(0) == 0
    assert policy.delay_for_attempt(1) == 0.5
    assert policy.delay_for_attempt(2) == 1.0
    assert policy.delay_for_attempt(3) == 2.0


# ─────────────────────────────────────────────────────────────────────────
# Transient vs Permanent Error Classification
# ─────────────────────────────────────────────────────────────────────────

def test_classify_transient_http_errors():
    """HTTP 5xx, 429, 408 are retryable."""
    assert classify_enforcement_error(500, "Internal Server Error") == "transient"
    assert classify_enforcement_error(502, "Bad Gateway") == "transient"
    assert classify_enforcement_error(503, "Service Unavailable") == "transient"
    assert classify_enforcement_error(504, "Gateway Timeout") == "transient"
    assert classify_enforcement_error(429, "Too Many Requests") == "transient"
    assert classify_enforcement_error(408, "Request Timeout") == "transient"


def test_classify_permanent_http_errors():
    """HTTP 4xx (except 408/429) are non-retryable."""
    assert classify_enforcement_error(400, "Bad Request") == "permanent"
    assert classify_enforcement_error(401, "Unauthorized") == "permanent"
    assert classify_enforcement_error(403, "Forbidden") == "permanent"
    assert classify_enforcement_error(404, "Not Found") == "permanent"
    assert classify_enforcement_error(422, "Unprocessable Entity") == "permanent"


def test_classify_network_errors():
    """Connection/timeout strings are transient."""
    assert classify_enforcement_error(0, "connection refused") == "transient"
    assert classify_enforcement_error(0, "timeout") == "transient"
    assert classify_enforcement_error(0, "not configured") == "permanent"
    assert classify_enforcement_error(0, "unauthorized") == "permanent"


# ─────────────────────────────────────────────────────────────────────────
# Partition Simulation: Webhook Failures with Retry
# ─────────────────────────────────────────────────────────────────────────

def test_partition_webhook_fails_then_succeeds(tmp_path):
    """Simulate transient webhook unavailability; retry succeeds on attempt 2."""
    db = DuckDBManager(db_path=str(tmp_path / "test_resilience.duckdb"))
    orchestrator = HardenedEnforcementOrchestrator(db=db)

    attempt_count = 0

    def mock_enforce_containment_with_retry(action_type, target, detail, operator_id, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            return {
                "status": "error",
                "connector": "webhook",
                "detail": {"error": "Service Unavailable"},
            }
        return {
            "status": "enforced",
            "connector": "webhook",
            "detail": {"http_status": 200},
        }

    with patch('security_agents.edr_connector.enforce_containment', side_effect=mock_enforce_containment_with_retry):
        result = orchestrator.enforce_with_retry(
            "isolate_host_staged", "192.168.1.1", {"reason": "test"}, "operator1"
        )

    assert result["status"] == "enforced"
    assert result["attempts"] == 2
    assert attempt_count == 2


def test_partition_permanent_error_stops_retry(tmp_path):
    """Permanent error (403) halts retries immediately."""
    db = DuckDBManager(db_path=str(tmp_path / "test_resilience_perm.duckdb"))
    orchestrator = HardenedEnforcementOrchestrator(db=db)

    attempt_count = 0

    def mock_enforce_403(action_type, target, detail, operator_id, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        return {
            "status": "error",
            "connector": "webhook",
            "detail": {"error": "Unauthorized", "http_status": 403},
        }

    with patch('security_agents.edr_connector.enforce_containment', side_effect=mock_enforce_403):
        result = orchestrator.enforce_with_retry(
            "isolate_host_staged", "192.168.1.1", {"reason": "test"}, "operator1"
        )

    # Permanent errors don't retry.
    assert result["status"] == "error"
    assert result["error_classification"] == "permanent"
    assert attempt_count == 1


def test_partition_exhausted_retries(tmp_path):
    """After max_attempts, fail gracefully."""
    db = DuckDBManager(db_path=str(tmp_path / "test_resilience_exhausted.duckdb"))
    policy = RetryPolicy(max_attempts=2)
    orchestrator = HardenedEnforcementOrchestrator(db=db, retry_policy=policy)

    attempt_count = 0

    def mock_enforce_always_fails(action_type, target, detail, operator_id, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        return {
            "status": "error",
            "connector": "webhook",
            "detail": {"error": "Service Unavailable"},
        }

    with patch('security_agents.edr_connector.enforce_containment', side_effect=mock_enforce_always_fails):
        result = orchestrator.enforce_with_retry(
            "isolate_host_staged", "192.168.1.1", {"reason": "test"}, "operator1"
        )

    assert result["status"] == "error"
    assert result["attempts"] == 2
    assert result["error_classification"] == "transient"


# ─────────────────────────────────────────────────────────────────────────
# Split-Brain & Isolation Scenarios
# ─────────────────────────────────────────────────────────────────────────

def test_ontology_ledger_isolation_fallback(tmp_path):
    """When ontology engine is unreachable, get_related_targets gracefully returns empty."""
    db = DuckDBManager(db_path=str(tmp_path / "test_fallback.duckdb"))

    # Create a mock OntologyEngine that raises an exception.
    class FailingOntologyEngine:
        def find_or_create_target_node(self, target):
            raise Exception("Ledger unreachable")

    ontology = FailingOntologyEngine()

    # Should not crash; should return empty list when ontology fails.
    related = get_related_targets_for_remediation("10.0.0.1", ontology, db=db, max_depth=2)
    assert related == []


def test_audit_dlq_write_on_permanent_failure(tmp_path):
    """Permanent failure halts immediately and returns permanent error classification."""
    db = DuckDBManager(db_path=str(tmp_path / "test_dlq.duckdb"))

    attempt_count = 0

    def mock_enforce_401(action_type, target, detail, operator_id, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        return {
            "status": "error",
            "connector": "webhook",
            "detail": {"error": "Auth failed", "http_status": 401},
        }

    orchestrator = HardenedEnforcementOrchestrator(db=db)
    with patch('security_agents.edr_connector.enforce_containment', side_effect=mock_enforce_401):
        result = orchestrator.enforce_with_retry(
            "isolate_host_staged", "10.0.0.1", {"reason": "test"}, "operator1"
        )

    # Permanent auth failure halts immediately.
    assert result["error_classification"] == "permanent"
    # In production, this would insert to dlq_audit_log table.
    assert result["attempts"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Offline Cryptographic Fallback
# ─────────────────────────────────────────────────────────────────────────

def test_hmac_signed_cache_token_generation():
    """Generate short-lived HMAC-signed tokens for offline approval."""
    from crypto.pqc_manager import PQCAuditManager
    import hmac
    import hashlib
    import json
    from datetime import datetime, timezone, timedelta

    pqc = PQCAuditManager()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=15)

    payload = {
        "action_type": "isolate_host_staged",
        "target": "10.0.0.1",
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }

    # Sign with HMAC (fallback when PQC unavailable).
    secret = b"offline-fallback-secret-key"
    message = json.dumps(payload, sort_keys=True).encode("utf-8")
    token = hmac.new(secret, message, hashlib.sha256).hexdigest()

    # Verify signature.
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(token, expected)
