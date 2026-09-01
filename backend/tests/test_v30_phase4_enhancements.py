"""
backend/tests/test_v30_phase4_enhancements.py
JAKAL v3.0 Phase 4 -- progressive enhancement of supporting strengths.

4.1 AIPCheatSheetEngine (payloads/aip_cheatsheet_engine.py): thin prompt ->
    matching-playbook lookup over the EXISTING playbook_library.PLAYBOOKS
    catalog. Deliberately no new DB table -- see that module's docstring.
4.2 tools.authorization.get_authorization_status(): read-only scope +
    insurance status, fails closed, used by
    ExploitAgent.get_enriched_approval_context()'s "authorization" field.
4.3 UnifiedSecurityFabric.capability_summary(): light "which of the 7
    capabilities are active" view over existing fabric_modules/
    fabric_events data.
4.4 Quantum job -> q_aip_inference_registry linking is exercised via
    routers/quantum.py's _link_finished_job_to_audit_trail(), tested
    directly against DuckDBManager + PQCAuditManager (no live Qiskit
    circuit needed -- this test constructs the "finished job" result
    shape run_circuit() would have returned).

Run: cd backend && python -m pytest tests/test_v30_phase4_enhancements.py -q
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
from payloads.aip_cheatsheet_engine import AIPCheatSheetEngine
from tools.authorization import get_authorization_status
from security_agents.unified_fabric import UnifiedSecurityFabric, FABRIC_CAPABILITIES


def _authorized_db(tmp_path, name="test_phase4.duckdb"):
    path = str(tmp_path / name)
    manager = DuckDBManager(db_path=path)
    now = datetime.now(timezone.utc)
    manager.add_scope("ACME", "10.0.0.0/24, acme.example.org",
                       now - timedelta(days=1), now + timedelta(days=30))
    manager.add_insurance_policy("P1", "Lloyds", 1_000_000, now + timedelta(days=365))
    return manager


# ---------------------------------------------------------------------------
# 4.1 -- AIPCheatSheetEngine
# ---------------------------------------------------------------------------

def test_query_ranks_playbooks_by_keyword_overlap():
    engine = AIPCheatSheetEngine()
    matches = engine.query("ransomware incident response network isolation", limit=3)
    assert matches
    assert matches[0]["score"] >= (matches[-1]["score"] if len(matches) > 1 else 0)
    top = matches[0]
    assert "playbook_key" in top and "recommended_scripts" in top and "parameters" in top


def test_query_empty_prompt_returns_no_matches():
    engine = AIPCheatSheetEngine()
    assert engine.query("", limit=5) == []
    assert engine.query("   ", limit=5) == []


def test_query_nonsense_prompt_returns_no_matches():
    engine = AIPCheatSheetEngine()
    assert engine.query("zzzqqqxxx nonexistent gibberish term", limit=5) == []


def test_recommend_for_payload_uses_technique_and_phase():
    engine = AIPCheatSheetEngine()
    rec = engine.recommend_for_payload("T1078", "detection", "lateral movement hunt")
    assert rec is not None
    assert rec["playbook_key"]


def test_recommend_for_payload_none_when_nothing_scores():
    engine = AIPCheatSheetEngine()
    assert engine.recommend_for_payload(None, None, None) is None


def test_engine_does_not_mutate_playbooks_source():
    from payloads.playbook_library import PLAYBOOKS
    before = len(PLAYBOOKS)
    engine = AIPCheatSheetEngine()
    engine.query("ransomware network isolation", limit=5)
    assert len(PLAYBOOKS) == before


def test_enriched_approval_context_includes_recommended_playbook(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    ctx = gate.get_enriched_approval_context(payload_id)
    assert "recommended_playbook" in ctx  # may be None or a match; key must exist
    db.conn.close()


# ---------------------------------------------------------------------------
# 4.2 -- Authorization Gate Visibility
# ---------------------------------------------------------------------------

def test_get_authorization_status_authorized_in_scope(tmp_path):
    db = _authorized_db(tmp_path)
    status = get_authorization_status("10.0.0.5", db=db)
    assert status == {"in_scope": True, "has_insurance": True, "authorized": True, "reason": None}
    db.conn.close()


def test_get_authorization_status_out_of_scope(tmp_path):
    db = _authorized_db(tmp_path)
    status = get_authorization_status("203.0.113.99", db=db)
    assert status["authorized"] is False
    assert status["in_scope"] is False
    assert "outside authorized scope" in status["reason"]
    db.conn.close()


def test_get_authorization_status_no_insurance(tmp_path):
    db = DuckDBManager(db_path=str(tmp_path / "no_insurance.duckdb"))
    now = datetime.now(timezone.utc)
    db.add_scope("ACME", "10.0.0.0/24", now - timedelta(days=1), now + timedelta(days=30))
    status = get_authorization_status("10.0.0.5", db=db)
    assert status["authorized"] is False
    assert status["has_insurance"] is False
    assert "no active insurance policy" in status["reason"]
    db.conn.close()


def test_get_authorization_status_never_writes_audit_log(tmp_path):
    """Read-only: calling this repeatedly must not spam pqc_audit_log or
    agent_logs the way check_authorization_and_scope() deliberately does."""
    db = _authorized_db(tmp_path)
    before_pqc = db.conn.execute("SELECT COUNT(*) FROM pqc_audit_log").fetchone()[0]
    before_logs = db.conn.execute("SELECT COUNT(*) FROM agent_logs").fetchone()[0]
    for _ in range(5):
        get_authorization_status("10.0.0.5", db=db)
    after_pqc = db.conn.execute("SELECT COUNT(*) FROM pqc_audit_log").fetchone()[0]
    after_logs = db.conn.execute("SELECT COUNT(*) FROM agent_logs").fetchone()[0]
    assert after_pqc == before_pqc
    assert after_logs == before_logs
    db.conn.close()


def test_get_authorization_status_fails_closed_on_error(tmp_path):
    class _BrokenDB:
        def query(self, *a, **kw):
            raise RuntimeError("simulated DB failure")

    status = get_authorization_status("10.0.0.5", db=_BrokenDB())
    assert status["authorized"] is False
    assert "authorization status check failed" in status["reason"]


def test_enriched_approval_context_includes_authorization(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    ctx = gate.get_enriched_approval_context(payload_id)
    assert ctx["authorization"] == {"in_scope": True, "has_insurance": True, "authorized": True, "reason": None}
    db.conn.close()


# ---------------------------------------------------------------------------
# 4.3 -- Light Unified Fabric Reporting
# ---------------------------------------------------------------------------

def test_capability_summary_covers_all_seven_capabilities(tmp_path):
    db = DuckDBManager(db_path=str(tmp_path / "fabric.duckdb"))
    fabric = UnifiedSecurityFabric(db=db)
    summary = fabric.capability_summary()
    assert summary["total_capabilities"] == len(FABRIC_CAPABILITIES) == 7
    assert len(summary["capabilities"]) == 7
    for cap in summary["capabilities"]:
        assert set(cap.keys()) == {
            "module_key", "label", "pillar", "status", "considered_active", "has_recorded_activity",
        }
    db.conn.close()


def test_capability_summary_reflects_recorded_activity(tmp_path):
    db = DuckDBManager(db_path=str(tmp_path / "fabric2.duckdb"))
    fabric = UnifiedSecurityFabric(db=db)
    key = next(iter(FABRIC_CAPABILITIES))

    before = fabric.capability_summary()
    before_cap = next(c for c in before["capabilities"] if c["module_key"] == key)
    assert before_cap["has_recorded_activity"] is False

    db.insert_fabric_event({
        "event_id": str(uuid.uuid4()), "module_key": key,
        "event_type": "test_event", "detail": "unit test", "severity": "info", "operator_id": "op1",
    })

    after = fabric.capability_summary()
    after_cap = next(c for c in after["capabilities"] if c["module_key"] == key)
    assert after_cap["has_recorded_activity"] is True
    db.conn.close()


# ---------------------------------------------------------------------------
# 4.4 -- Quantum Job Linking
# ---------------------------------------------------------------------------

def test_finished_quantum_job_links_to_qaip_registry(tmp_path):
    from routers.quantum import _link_finished_job_to_audit_trail
    from schemas import QuantumJobRequest

    db = DuckDBManager(db_path=str(tmp_path / "quantum.duckdb"))
    import routers.quantum as quantum_router_module
    orig_get_db_manager = None
    import database
    orig_get_db_manager = database.get_db_manager
    database.get_db_manager = lambda *a, **kw: db
    try:
        req = QuantumJobRequest(circuit="bell_state", shots=1024, backend="qiskit_aer",
                                 operator_id="op1", related_approval_id="approval-123")
        result = {
            "status": "completed", "backend": "qiskit_aer", "shots": 1024,
            "circuit_depth": 3, "num_qubits": 2, "execution_time_ms": 12.3,
        }
        inference_id = _link_finished_job_to_audit_trail("job-abc", req, result)
        assert inference_id is not None

        row = db.conn.execute(
            "SELECT circuit_type, execution_metrics_json, operator_id FROM q_aip_inference_registry "
            "WHERE inference_id = ?", (inference_id,),
        ).fetchone()
        assert row is not None
        import json
        metrics = json.loads(row[1])
        assert row[0] == "bell_state"
        assert row[2] == "op1"
        assert metrics["related_approval_id"] == "approval-123"
        assert metrics["job_id"] == "job-abc"
    finally:
        database.get_db_manager = orig_get_db_manager
        db.conn.close()


def test_link_failure_returns_none_not_raises(tmp_path):
    from routers.quantum import _link_finished_job_to_audit_trail
    from schemas import QuantumJobRequest

    import database
    orig_get_db_manager = database.get_db_manager

    def _broken_get_db_manager(*a, **kw):
        raise RuntimeError("simulated failure")

    database.get_db_manager = _broken_get_db_manager
    try:
        req = QuantumJobRequest(circuit="bell_state")
        result = {"status": "completed"}
        assert _link_finished_job_to_audit_trail("job-x", req, result) is None
    finally:
        database.get_db_manager = orig_get_db_manager
