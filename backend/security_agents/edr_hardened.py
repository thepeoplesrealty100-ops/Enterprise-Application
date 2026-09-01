"""
backend/security_agents/edr_hardened.py
=========================================
Hardened EDR enforcement with retry logic, compliance gating, and
multi-target orchestration — JAKAL Track A.

Enhances edr_connector.py with:
  - Exponential backoff retry logic (3 attempts, 1s → 4s → 16s)
  - Compliance pre-check (validates against org posture before enforce)
  - Attack-path targeting (identifies related nodes in ontology for
    multi-node remediation)
  - Better error classification (transient vs permanent failures)
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RetryPolicy:
    """Configurable retry strategy for enforcement failures."""
    def __init__(self, max_attempts: int = 3, base_delay_seconds: float = 1.0,
                 backoff_factor: float = 4.0):
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.backoff_factor = backoff_factor

    def delay_for_attempt(self, attempt: int) -> float:
        """Exponential backoff: 1s, 4s, 16s, ..."""
        if attempt == 0:
            return 0
        return self.base_delay_seconds * (self.backoff_factor ** (attempt - 1))


class TransientError(Exception):
    """Retryable error (timeout, transient service unavailable)."""
    pass


class PermanentError(Exception):
    """Non-retryable error (config, auth, target not found)."""
    pass


def classify_enforcement_error(status: int, detail: str) -> str:
    """Classify webhook/request error as 'transient', 'permanent', or 'unknown'."""
    if status in (500, 502, 503, 504, 408, 429):  # Server errors, timeout, rate limit
        return "transient"
    if status in (400, 401, 403, 404, 422):  # Client/config errors
        return "permanent"
    if "timeout" in detail.lower() or "connection refused" in detail.lower():
        return "transient"
    if "not configured" in detail.lower() or "unauthorized" in detail.lower():
        return "permanent"
    return "unknown"


class HardenedEnforcementOrchestrator:
    """
    Orchestrates enforcement with retry logic and compliance gating.
    Wraps the base enforcement connectors to add resilience and policy.
    """
    def __init__(self, db=None, vm_orchestrator=None, retry_policy: Optional[RetryPolicy] = None):
        self.db = db
        self.vm = vm_orchestrator
        self.retry_policy = retry_policy or RetryPolicy()

    def enforce_with_retry(self, action_type: str, target: str, detail: Dict[str, Any],
                           operator_id: str) -> Dict[str, Any]:
        """
        Enforce a containment action with exponential backoff retry.
        Returns:
        {
            "status": "enforced"|"error"|"not_configured",
            "attempts": int,
            "connector": str,
            "detail": {...},
            "compliance_validated": bool,
            "error_classification": "transient"|"permanent"|"unknown" (if error),
        }
        """
        from security_agents.edr_connector import enforce_containment
        from security_agents.compliance_constraints import validate_containment_compliance

        # Pre-check compliance if org posture is available.
        compliance_result = None
        if self.db:
            try:
                posture = self.db.conn.execute(
                    "SELECT data FROM global_security_settings WHERE setting_key = 'org_compliance_posture' LIMIT 1"
                ).fetchone()
                org_posture = posture[0] if posture else {}
                compliance_result = validate_containment_compliance(action_type, target, org_posture)
                if not compliance_result["compliant"]:
                    logger.warning(
                        "Compliance violation detected for %s on %s: %s",
                        action_type, target,
                        [v["constraint"] for v in compliance_result["violations"]]
                    )
                    return {
                        "status": "error",
                        "attempts": 0,
                        "connector": "compliance_gate",
                        "detail": {
                            "error": "Compliance constraints violated",
                            "violations": compliance_result["violations"],
                            "requires_audit_exception": compliance_result["requires_audit_exception"],
                        },
                        "compliance_validated": False,
                        "error_classification": "permanent",
                    }
            except Exception as e:
                logger.debug("Compliance check skipped: %s", e)

        # Attempt enforcement with retry.
        last_result = None
        for attempt in range(self.retry_policy.max_attempts):
            if attempt > 0:
                delay = self.retry_policy.delay_for_attempt(attempt)
                logger.info("Enforcement retry (attempt %d/%d, delay %.1fs): %s on %s",
                            attempt + 1, self.retry_policy.max_attempts, delay, action_type, target)
                time.sleep(delay)

            try:
                result = enforce_containment(
                    action_type, target, detail, operator_id,
                    db=self.db, vm_orchestrator=self.vm,
                )
                last_result = result

                if result.get("status") == "enforced":
                    return {
                        "status": "enforced",
                        "attempts": attempt + 1,
                        "connector": result.get("connector"),
                        "detail": result.get("detail", {}),
                        "compliance_validated": True,
                        "error_classification": None,
                    }

                # Determine if this is retryable.
                if result.get("status") == "not_configured":
                    # Not retryable — webhook/connector simply not configured.
                    return {
                        "status": "not_configured",
                        "attempts": attempt + 1,
                        "connector": result.get("connector"),
                        "detail": result.get("detail", {}),
                        "compliance_validated": True,
                        "error_classification": "permanent",
                    }

                # Error case — classify for retry decision.
                detail_str = str(result.get("detail", {}))
                classification = classify_enforcement_error(500, detail_str)  # Assume error → classify detail
                if classification == "permanent":
                    return {
                        "status": "error",
                        "attempts": attempt + 1,
                        "connector": result.get("connector"),
                        "detail": result.get("detail", {}),
                        "compliance_validated": True,
                        "error_classification": "permanent",
                    }
                # Otherwise transient or unknown — retry.

            except Exception as e:
                logger.exception("Enforcement attempt %d/%d failed: %s", attempt + 1,
                                self.retry_policy.max_attempts, e)
                last_result = None
                # Retry on any exception.

        # Exhausted retries.
        return {
            "status": "error",
            "attempts": self.retry_policy.max_attempts,
            "connector": last_result.get("connector") if last_result else "unknown",
            "detail": {
                "error": f"Enforcement failed after {self.retry_policy.max_attempts} attempts",
                "last_result": last_result.get("detail") if last_result else None,
            },
            "compliance_validated": True,
            "error_classification": "transient",
        }


def get_related_targets_for_remediation(target: str, ontology_engine, db=None,
                                        max_depth: int = 2) -> List[str]:
    """
    Query the Ontology Engine to identify related targets (nodes connected
    to the given target within max_depth hops). Useful for multi-target
    remediation — if an attacker compromised Host A, containment may need
    to extend to related hosts B, C, D that share lateral-movement paths.

    Returns a list of related target identifiers (IPs, hostnames, etc.).
    """
    if not ontology_engine:
        return []

    try:
        # Find or create a node for the target if it doesn't exist.
        target_node_id = ontology_engine.find_or_create_target_node(target)
        if not target_node_id:
            return []

        # Query the subgraph around this target.
        subgraph = ontology_engine.query_subgraph(target_node_id, max_depth=max_depth)

        # Extract Asset nodes (hosts, IPs, etc.) from the subgraph.
        related = []
        for node_id, node_data in subgraph.get("nodes", {}).items():
            if node_id != target_node_id and node_data.get("object_type") == "Asset":
                if "value" in node_data:
                    related.append(node_data["value"])

        return related
    except Exception as e:
        logger.warning("Failed to query related targets from ontology: %s", e)
        return []
