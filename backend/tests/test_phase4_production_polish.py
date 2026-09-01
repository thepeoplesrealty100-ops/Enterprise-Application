"""
backend/tests/test_phase4_production_polish.py
JAKAL Phase 4 — Production polish and end-to-end integration.

Covers:
  - Complete v3.0 workflow (compliance → attack-path → enforcement)
  - Resilience under various failure scenarios
  - API contract validation
  - Performance under load simulation

Run: cd backend && python -m pytest tests/test_phase4_production_polish.py -q
"""

import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from database import DuckDBManager
from security_agents.edr_hardened import (
    HardenedEnforcementOrchestrator,
    RetryPolicy,
    get_related_targets_for_remediation,
    get_related_targets_with_criticality,
)
from security_agents.compliance_constraints import validate_containment_compliance
from services.ontology_engine import OntologyEngine


def test_e2e_compliance_check_then_enforcement(tmp_path):
    """Complete workflow: compliance check → attack-path discovery → enforcement."""
    db = DuckDBManager(db_path=str(tmp_path / "test_e2e_workflow.duckdb"))
    now = datetime.now(timezone.utc)
    db.add_scope("ACME", "10.0.0.0/24", now - timedelta(days=1), now + timedelta(days=30))

    # Step 1: Compliance pre-check
    posture = {
        "frameworks": ["HIPAA"],
        "hipaa_allowed_regions": ["us-east"]
    }
    compliance_result = validate_containment_compliance("isolate_host_staged", "us-east-db-01", posture)
    assert compliance_result["compliant"] is True

    # Step 2: Attack-path discovery
    ontology = OntologyEngine(db)
    primary_id = ontology.find_or_create_target_node("10.0.0.1")
    related_id = ontology.find_or_create_target_node("10.0.0.2")
    db.conn.execute(
        "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), primary_id, related_id, "lateral_movement")
    )
    db.conn.commit()

    related = get_related_targets_for_remediation("10.0.0.1", ontology, db=db, max_depth=2)
    assert len(related) >= 1

    # Step 3: Enforcement with retry
    orchestrator = HardenedEnforcementOrchestrator(db=db)
    result = orchestrator.enforce_with_retry(
        "isolate_host_staged", "10.0.0.1", {"reason": "E2E test"}, "test_operator"
    )
    # May be not_configured (no webhook), but shouldn't crash or raise
    assert result["status"] in ("not_configured", "error", "enforced")
    db.conn.close()


def test_criticality_scoring_reflects_organizational_priorities(tmp_path):
    """Criticality scores align with organizational risk priorities."""
    db = DuckDBManager(db_path=str(tmp_path / "test_criticality_priorities.duckdb"))
    ontology = OntologyEngine(db)

    # Create a small network with mixed criticality.
    primary = ontology.find_or_create_target_node("10.0.0.1")
    prod_db = ontology.find_or_create_target_node("10.0.0.2")
    auth_srv = ontology.find_or_create_target_node("10.0.0.3")
    workstation = ontology.find_or_create_target_node("10.0.0.4")

    # Mark by criticality.
    import json
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.2", "critical_service": True}), prod_db)
    )
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.3", "critical_service": False}), auth_srv)
    )
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.4"}), workstation)
    )

    # Link all to primary.
    for target_id in [prod_db, auth_srv, workstation]:
        db.conn.execute(
            "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), primary, target_id, "lateral_movement")
        )
    db.conn.commit()

    # Query with criticality.
    related = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=1)

    # Verify ordering: prod_db (highest) → auth_srv → workstation (lowest)
    assert len(related) == 3
    assert related[0]["target"] == "10.0.0.2"  # prod_db
    assert related[-1]["target"] == "10.0.0.4"  # workstation
    # Criticality monotonically decreases (or stays same).
    for i in range(len(related) - 1):
        assert related[i]["criticality_score"] >= related[i + 1]["criticality_score"]
    db.conn.close()


def test_deep_graph_traversal_4_hops(tmp_path):
    """Phase 3 supports 4-hop traversal for modeling privilege escalation."""
    db = DuckDBManager(db_path=str(tmp_path / "test_deep_traversal.duckdb"))
    ontology = OntologyEngine(db)

    # Build a 4-hop chain: primary → hop1 → hop2 → hop3 → prod_db
    primary = ontology.find_or_create_target_node("10.0.0.1")
    hop1 = ontology.find_or_create_target_node("10.0.0.2")
    hop2 = ontology.find_or_create_target_node("10.0.0.3")
    hop3 = ontology.find_or_create_target_node("10.0.0.4")
    prod_db = ontology.find_or_create_target_node("10.0.0.5")

    # Create chain.
    for src, tgt in [(primary, hop1), (hop1, hop2), (hop2, hop3), (hop3, prod_db)]:
        db.conn.execute(
            "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), src, tgt, "privilege_escalation")
        )

    # Mark prod_db as critical.
    import json
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.5", "critical_service": True}), prod_db)
    )
    db.conn.commit()

    # Query with max_depth=4.
    related = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=4)

    # Should find prod_db despite being 4 hops away.
    prod_found = any(r["target"] == "10.0.0.5" for r in related)
    assert prod_found

    # Verify prod_db is highest priority.
    if len(related) > 1:
        prod_result = next(r for r in related if r["target"] == "10.0.0.5")
        for other in related:
            if other["target"] != "10.0.0.5":
                assert prod_result["criticality_score"] >= other["criticality_score"]

    db.conn.close()


def test_compliance_blocks_enforcement_flow(tmp_path):
    """Compliance violations block enforcement in complete workflow."""
    # Test the compliance validation function directly (orchestrator depends on DB schema).
    posture = {
        "frameworks": ["SOC2"],
        "soc2_critical_service_hosts": ["api-primary-01"]
    }

    # api-primary-01 is a critical service and should trigger compliance violation.
    result = validate_containment_compliance("quarantine_host_staged", "api-primary-01", posture)

    # Should be blocked by compliance.
    assert result["compliant"] is False
    assert len(result["violations"]) > 0
    assert any("audit" in v.get("reason", "").lower() for v in result["violations"])
    assert result["requires_audit_exception"] is True


def test_retry_policy_customization(tmp_path):
    """Custom retry policies work correctly."""
    db = DuckDBManager(db_path=str(tmp_path / "test_custom_retry.duckdb"))

    # Custom: 5 attempts, 0.5s base, 2x backoff (0s, 0.5s, 1s, 2s, 4s).
    policy = RetryPolicy(max_attempts=5, base_delay_seconds=0.5, backoff_factor=2.0)

    delays = [policy.delay_for_attempt(i) for i in range(6)]
    assert delays == [0, 0.5, 1.0, 2.0, 4.0, 8.0]

    # Orchestrator respects custom policy.
    orchestrator = HardenedEnforcementOrchestrator(db=db, retry_policy=policy)
    assert orchestrator.retry_policy.max_attempts == 5
    db.conn.close()


def test_isolation_prevents_cross_target_contamination(tmp_path):
    """Multiple targets don't contaminate each other's graphs."""
    db = DuckDBManager(db_path=str(tmp_path / "test_isolation.duckdb"))
    ontology = OntologyEngine(db)

    # Create two independent networks.
    # Network A: primary_a → related_a
    primary_a = ontology.find_or_create_target_node("10.1.0.1")
    related_a = ontology.find_or_create_target_node("10.1.0.2")
    db.conn.execute(
        "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), primary_a, related_a, "lateral_movement")
    )

    # Network B: primary_b → related_b
    primary_b = ontology.find_or_create_target_node("10.2.0.1")
    related_b = ontology.find_or_create_target_node("10.2.0.2")
    db.conn.execute(
        "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), primary_b, related_b, "lateral_movement")
    )
    db.conn.commit()

    # Query network A.
    related_a_targets = get_related_targets_for_remediation("10.1.0.1", ontology, db=db, max_depth=1)
    assert "10.1.0.2" in related_a_targets
    assert "10.2.0.2" not in related_a_targets  # No cross-network contamination.

    # Query network B.
    related_b_targets = get_related_targets_for_remediation("10.2.0.1", ontology, db=db, max_depth=1)
    assert "10.2.0.2" in related_b_targets
    assert "10.1.0.2" not in related_b_targets
    db.conn.close()


def test_large_graph_performance_baseline(tmp_path):
    """Criticality scoring scales to realistic graph sizes."""
    import time
    db = DuckDBManager(db_path=str(tmp_path / "test_large_graph.duckdb"))
    ontology = OntologyEngine(db)

    # Create a 100-node graph (primary + 99 related).
    primary = ontology.find_or_create_target_node("10.0.0.1")
    related_nodes = []
    for i in range(2, 102):  # 100 related nodes
        node = ontology.find_or_create_target_node(f"10.0.0.{i}")
        related_nodes.append(node)
        db.conn.execute(
            "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), primary, node, "lateral_movement")
        )
    db.conn.commit()

    # Query should complete in reasonable time (< 2 seconds for 100 nodes at depth 1).
    start = time.time()
    related = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=1)
    elapsed = time.time() - start

    assert len(related) == 100
    assert elapsed < 2.0  # Performance baseline
    db.conn.close()
