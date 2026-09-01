"""
backend/tests/test_phase3_attack_paths.py
JAKAL Phase 3 — Advanced attack-path heuristics with criticality scoring.

Covers:
  - Asset criticality scoring (production status, service type, confidence)
  - Related targets with criticality up to 4 hops
  - Phase 3 /related-targets-v3 endpoint validation
  - Multi-hop attack chain modeling

Run: cd backend && python -m pytest tests/test_phase3_attack_paths.py -q
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
    get_related_targets_with_criticality,
    score_asset_criticality,
)
from services.ontology_engine import OntologyEngine


def test_score_asset_criticality_production_database():
    """Production databases score high."""
    node_data = {
        "object_type": "Asset",
        "attributes": {"target": "prod-db-primary-01", "critical_service": True},
        "confidence": 0.9,
    }
    score = score_asset_criticality(node_data)
    # Expected: 0.4 (critical) + 0.2 (prod) + 0.15 (db) + 0.09 (confidence 0.9 * 0.1)
    assert score >= 0.7  # At least 0.74


def test_score_asset_criticality_auth_service():
    """Auth services score high."""
    node_data = {
        "object_type": "Asset",
        "attributes": {"target": "auth-service-prod", "critical_service": False},
        "confidence": 0.8,
    }
    score = score_asset_criticality(node_data)
    # Expected: 0.2 (prod) + 0.15 (auth) + 0.08 (confidence)
    assert score >= 0.4


def test_score_asset_criticality_regular_host():
    """Regular hosts score lower."""
    node_data = {
        "object_type": "Asset",
        "attributes": {"target": "workstation-01", "critical_service": False},
        "confidence": 0.5,
    }
    score = score_asset_criticality(node_data)
    # Expected: only 0.05 (confidence 0.5 * 0.1)
    assert score <= 0.15


def test_score_asset_criticality_no_attributes():
    """Handles missing attributes gracefully."""
    node_data = {
        "object_type": "Asset",
        "attributes": {},
        "confidence": 0.0,
    }
    score = score_asset_criticality(node_data)
    assert 0.0 <= score <= 1.0


def test_related_targets_with_criticality_single_level(tmp_path):
    """Single-hop related targets are scored correctly."""
    db = DuckDBManager(db_path=str(tmp_path / "test_criticality.duckdb"))
    ontology = OntologyEngine(db)

    # Create primary target.
    primary_id = ontology.find_or_create_target_node("10.0.0.1")

    # Create related production database.
    prod_db_id = ontology.find_or_create_target_node("10.0.0.2")
    db.conn.execute(
        "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), primary_id, prod_db_id, "lateral_movement")
    )

    # Create related regular workstation.
    ws_id = ontology.find_or_create_target_node("10.0.0.3")
    db.conn.execute(
        "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), primary_id, ws_id, "lateral_movement")
    )
    db.conn.commit()

    # Update prod-db node attributes for scoring.
    import json
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.2", "critical_service": True}), prod_db_id)
    )
    db.conn.commit()

    # Query related targets with criticality.
    related = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=1)

    # Should have 2 related targets, prod-db scoring higher.
    assert len(related) == 2
    assert related[0]["criticality_score"] >= related[1]["criticality_score"]
    assert related[0]["depth"] <= 1
    db.conn.close()


def test_related_targets_with_criticality_multi_hop(tmp_path):
    """Multi-hop paths model attack chains correctly."""
    db = DuckDBManager(db_path=str(tmp_path / "test_multi_hop.duckdb"))
    ontology = OntologyEngine(db)

    # Chain: primary → hop1 → hop2 → hop3 → production_db
    primary_id = ontology.find_or_create_target_node("10.0.0.1")
    hop1_id = ontology.find_or_create_target_node("10.0.0.2")
    hop2_id = ontology.find_or_create_target_node("10.0.0.3")
    hop3_id = ontology.find_or_create_target_node("10.0.0.4")
    prod_id = ontology.find_or_create_target_node("10.0.0.5")

    # Link chain.
    for src, tgt in [(primary_id, hop1_id), (hop1_id, hop2_id), (hop2_id, hop3_id), (hop3_id, prod_id)]:
        db.conn.execute(
            "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), src, tgt, "exploit_path")
        )

    # Mark prod as production database.
    import json
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.5", "critical_service": True}), prod_id)
    )
    db.conn.commit()

    # Query with max_depth=4 (deep).
    related = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=4)

    # Should find prod-db (depth 4) along with intermediate hops.
    assert len(related) >= 1
    prod_in_results = any(r["target"] == "10.0.0.5" for r in related)
    assert prod_in_results

    # Production database should score higher than intermediate hops.
    prod_result = next(r for r in related if r["target"] == "10.0.0.5")
    assert prod_result["criticality_score"] >= 0.4  # Critical service flag.
    db.conn.close()


def test_related_targets_with_criticality_respects_max_depth(tmp_path):
    """Respects max_depth limit."""
    db = DuckDBManager(db_path=str(tmp_path / "test_depth_limit.duckdb"))
    ontology = OntologyEngine(db)

    # Build a 3-hop chain.
    n1 = ontology.find_or_create_target_node("10.0.0.1")
    n2 = ontology.find_or_create_target_node("10.0.0.2")
    n3 = ontology.find_or_create_target_node("10.0.0.3")

    db.conn.execute(
        "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), n1, n2, "lateral_movement")
    )
    db.conn.execute(
        "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), n2, n3, "lateral_movement")
    )
    db.conn.commit()

    # Query with max_depth=1 (shallow).
    related_shallow = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=1)
    # Should find only 10.0.0.2 (depth 1).
    assert len(related_shallow) == 1
    assert related_shallow[0]["target"] == "10.0.0.2"

    # Query with max_depth=2 (deeper).
    related_deep = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=2)
    # Should find both 10.0.0.2 and 10.0.0.3.
    assert len(related_deep) == 2
    db.conn.close()


def test_related_targets_with_criticality_sorting(tmp_path):
    """Results sorted by criticality (descending) then depth (ascending)."""
    db = DuckDBManager(db_path=str(tmp_path / "test_sorting.duckdb"))
    ontology = OntologyEngine(db)

    primary_id = ontology.find_or_create_target_node("10.0.0.1")

    # Create 3 targets at same depth but different criticality.
    crit_target_id = ontology.find_or_create_target_node("10.0.0.2")  # Production DB
    normal_target_id = ontology.find_or_create_target_node("10.0.0.3")  # Normal
    low_target_id = ontology.find_or_create_target_node("10.0.0.4")  # Workstation

    # Mark targets.
    import json
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.2", "critical_service": True}), crit_target_id)
    )
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.3"}), normal_target_id)
    )
    db.conn.execute(
        "UPDATE ontological_object_nodes SET attributes_json = ? WHERE node_id = ?",
        (json.dumps({"target": "10.0.0.4", "critical_service": False}), low_target_id)
    )

    # Link all at same depth.
    for target_id in [crit_target_id, normal_target_id, low_target_id]:
        db.conn.execute(
            "INSERT INTO lattice_edge_telemetry (telemetry_id, source_node, target_node, event_type) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), primary_id, target_id, "lateral_movement")
        )
    db.conn.commit()

    related = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=1)

    # First should be critical service (highest criticality).
    assert related[0]["target"] == "10.0.0.2"
    # Verify criticality scores are descending.
    for i in range(len(related) - 1):
        assert related[i]["criticality_score"] >= related[i + 1]["criticality_score"]
    db.conn.close()


def test_related_targets_with_criticality_empty_graph(tmp_path):
    """Handles isolated node gracefully."""
    db = DuckDBManager(db_path=str(tmp_path / "test_empty.duckdb"))
    ontology = OntologyEngine(db)

    # Create isolated node with no edges.
    _ = ontology.find_or_create_target_node("10.0.0.1")

    # Query should return empty list.
    related = get_related_targets_with_criticality("10.0.0.1", ontology, db=db, max_depth=2)
    assert related == []
    db.conn.close()
