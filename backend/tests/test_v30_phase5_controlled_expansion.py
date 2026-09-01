"""
backend/tests/test_v30_phase5_controlled_expansion.py
JAKAL v3.0 Phase 5 -- controlled expansion.

Covers:
  - services/ontology_engine.py's materialize_action_link()/
    find_or_create_target_node(): staged payloads and containment
    actions now get a real position in the Ontology Engine's graph.
  - ExploitAgent.get_enriched_approval_context()'s new "ontology" field:
    a basic attack-path/related-object view built from that graph.
  - Any real remediation/quarantine/isolation action (routers/response.py's
    quarantine-host / isolate-host / triage auto-stage) now goes through
    the same Maya-gated Approval Gate as an offensive HIGH/CRITICAL
    payload -- regression-guards the gap found while building this: those
    action_types create their approval_requests row directly (not via
    stage_payloads()), so they never got a Maya challenge before this
    phase, meaning approve_payload() let them through unimpeded.

Run: cd backend && python -m pytest tests/test_v30_phase5_controlled_expansion.py -q
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
from security_agents.exploit_agent import ExploitAgent
from services.ontology_engine import OntologyEngine


def _authorized_db(tmp_path, name="test_phase5.duckdb"):
    path = str(tmp_path / name)
    manager = DuckDBManager(db_path=path)
    now = datetime.now(timezone.utc)
    manager.add_scope("ACME", "10.0.0.0/24, acme.example.org",
                       now - timedelta(days=1), now + timedelta(days=30))
    manager.add_insurance_policy("P1", "Lloyds", 1_000_000, now + timedelta(days=365))
    return manager


# ---------------------------------------------------------------------------
# OntologyEngine.materialize_action_link() / find_or_create_target_node()
# ---------------------------------------------------------------------------

def test_find_or_create_target_node_reuses_asset(tmp_path):
    db = DuckDBManager(db_path=str(tmp_path / "ontology1.duckdb"))
    engine = OntologyEngine(db)
    id1 = engine.find_or_create_target_node("10.0.0.5")
    id2 = engine.find_or_create_target_node("10.0.0.5")
    id3 = engine.find_or_create_target_node("10.0.0.9")
    assert id1 == id2
    assert id1 != id3
    db.conn.close()


def test_materialize_action_link_creates_node_and_edge(tmp_path):
    db = DuckDBManager(db_path=str(tmp_path / "ontology2.duckdb"))
    engine = OntologyEngine(db)
    node_id = engine.materialize_action_link("10.0.0.5", "StagedPayload", {"payload_id": "p1"})
    assert node_id is not None
    subgraph = engine.query_subgraph(node_id, max_depth=1)
    assert node_id in subgraph["nodes"]
    assert len(subgraph["nodes"]) == 2  # the action node + the Asset node
    assert len(subgraph["edges"]) == 1
    db.conn.close()


def test_materialize_action_link_none_for_empty_target(tmp_path):
    db = DuckDBManager(db_path=str(tmp_path / "ontology3.duckdb"))
    engine = OntologyEngine(db)
    assert engine.materialize_action_link("", "StagedPayload", {}) is None
    assert engine.materialize_action_link(None, "StagedPayload", {}) is None
    db.conn.close()


# ---------------------------------------------------------------------------
# get_enriched_approval_context()'s "ontology" field
# ---------------------------------------------------------------------------

def test_enriched_context_includes_ontology_for_staged_payload(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]

    ctx = gate.get_enriched_approval_context(payload_id)
    assert ctx["ontology"] is not None
    assert ctx["ontology"]["object_type"] == "StagedPayload"
    assert ctx["ontology"]["related_object_count"] >= 1  # at least the linked Asset node
    assert "subgraph" in ctx["ontology"]
    db.conn.close()


def test_enriched_context_ontology_shared_asset_across_payloads(tmp_path):
    """Two payloads staged against the same target should share one
    Asset node -- proof the graph is actually being built, not just a
    disconnected node per payload."""
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged1 = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],
        target="10.0.0.5", operator_id="op1",
    )
    staged2 = gate.stage_payloads(
        [{"technique_id": "T1190", "finding": "x"}],
        target="10.0.0.5", operator_id="op1",
    )
    ctx1 = gate.get_enriched_approval_context(staged1[0]["payload_id"])
    ctx2 = gate.get_enriched_approval_context(staged2[0]["payload_id"])

    asset_ids_1 = {n for n, v in ctx1["ontology"]["subgraph"]["nodes"].items() if v["object_type"] == "Asset"}
    asset_ids_2 = {n for n, v in ctx2["ontology"]["subgraph"]["nodes"].items() if v["object_type"] == "Asset"}
    assert asset_ids_1 == asset_ids_2
    assert len(asset_ids_1) == 1
    db.conn.close()


def test_enriched_context_ontology_none_when_no_target(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],
        target="", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    ctx = gate.get_enriched_approval_context(payload_id)
    assert ctx["ontology"] is None
    db.conn.close()


# ---------------------------------------------------------------------------
# Real remediation/quarantine/isolation actions go through the Maya-gated
# Approval Gate -- the actual v3.0 Phase 5 requirement.
# ---------------------------------------------------------------------------

def test_response_router_maya_helper_attaches_challenge_for_high_risk(tmp_path):
    from routers.response import _maybe_attach_maya_challenge
    import routers.response as response_module
    db = _authorized_db(tmp_path)
    original_gate = response_module._gate
    response_module._gate = ExploitAgent(db_manager=db)
    try:
        request_id = str(uuid.uuid4())
        db.create_approval_request({
            "request_id": request_id, "requested_by": "op1",
            "action_type": "isolate_host_staged", "target": "10.0.0.5",
            "risk_level": "HIGH", "summary": "test isolation",
        })
        challenge = _maybe_attach_maya_challenge(request_id, "op1", "HIGH")
        assert challenge is not None
        assert challenge["status"] == "pending"

        # And the interlock actually blocks approval until consumed --
        # same as an offensive payload.
        blocked = response_module._gate.approve_payload(request_id, "op1", "authorized")
        assert blocked["status"] == "error"

        consumed = db.consume_maya_session(challenge["session_id"], challenge["challenge_token"], "op1")
        assert consumed["status"] == "consumed"

        approved = response_module._gate.approve_payload(request_id, "op1", "authorized")
        assert approved["status"] == "approved"
    finally:
        response_module._gate = original_gate
        db.conn.close()


def test_response_router_maya_helper_none_for_low_medium_risk(tmp_path):
    from routers.response import _maybe_attach_maya_challenge
    import routers.response as response_module
    db = _authorized_db(tmp_path)
    original_gate = response_module._gate
    response_module._gate = ExploitAgent(db_manager=db)
    try:
        request_id = str(uuid.uuid4())
        db.create_approval_request({
            "request_id": request_id, "requested_by": "op1",
            "action_type": "response_containment", "target": "10.0.0.5",
            "risk_level": "MEDIUM", "summary": "test",
        })
        assert _maybe_attach_maya_challenge(request_id, "op1", "MEDIUM") is None
    finally:
        response_module._gate = original_gate
        db.conn.close()


def test_response_router_ontology_materialization(tmp_path):
    from routers.response import _materialize_containment_ontology_link
    import routers.response as response_module
    db = _authorized_db(tmp_path)
    original_db = response_module._db
    response_module._db = db
    try:
        request_id = str(uuid.uuid4())
        _materialize_containment_ontology_link(request_id, "10.0.0.5", "isolate_host_staged", "op1")

        node = db.find_ontological_node_by_attribute(None, "payload_id", request_id)
        assert node is not None
        assert node["object_type"] == "ContainmentAction"
    finally:
        response_module._db = original_db
        db.conn.close()
