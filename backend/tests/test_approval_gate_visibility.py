"""
backend/tests/test_approval_gate_visibility.py
JAKAL v3.0 Phase 3 -- core loop visibility / Zero Trust alignment.

Covers ExploitAgent.get_enriched_approval_context() (risk level, blast
radius, reversibility, Maya session linkage, PQC re-verification, status
timeline) and crypto.pqc_manager.verify_stored_entry() (re-verifying a
persisted pqc_audit_log row against its OWN recorded public key/
algorithm, not a live manager instance's key -- see that function's
docstring for why that distinction matters).

Also regression-guards a real bug found while building this: ExploitAgent
._sign() was storing action_detail as `payload` alone, but
sign_agent_action() actually signed `{"action_type": action_type,
**payload}` -- so any attempt to re-verify a stored ExploitAgent entry
against its own recorded payload_hash always failed the integrity
pre-check. Fixed by making the stored action_detail byte-consistent
(sort_keys=True, action_type merged in) with what was actually signed.

Run: cd backend && python -m pytest tests/test_approval_gate_visibility.py -q
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
from crypto.pqc_manager import verify_stored_entry


def _authorized_db(tmp_path, name="test_visibility.duckdb"):
    path = str(tmp_path / name)
    manager = DuckDBManager(db_path=path)
    now = datetime.now(timezone.utc)
    manager.add_scope("ACME", "10.0.0.0/24, acme.example.org",
                       now - timedelta(days=1), now + timedelta(days=30))
    manager.add_insurance_policy("P1", "Lloyds", 1_000_000, now + timedelta(days=365))
    return manager


def test_context_none_for_unknown_payload(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    assert gate.get_enriched_approval_context(str(uuid.uuid4())) is None
    db.conn.close()


def test_context_reflects_risk_blast_radius_reversibility(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1595", "phase": "recon_active"}],  # -> LOW risk
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]

    ctx = gate.get_enriched_approval_context(payload_id)
    assert ctx["risk_level"] == "LOW"
    assert ctx["reversible"] is True
    assert "blast radius" in ctx["blast_radius_summary"].lower()
    assert ctx["maya_session_id"] is None       # LOW risk never gets a Maya challenge
    assert ctx["maya_session_status"] is None
    db.conn.close()


def test_context_high_risk_is_irreversible_and_links_maya_session(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],  # -> HIGH risk
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    maya = staged[0]["maya_challenge"]

    ctx = gate.get_enriched_approval_context(payload_id)
    assert ctx["risk_level"] == "HIGH"
    assert ctx["reversible"] is False
    assert ctx["maya_session_id"] == maya["session_id"]
    assert ctx["maya_session_status"] == "pending"
    assert isinstance(ctx["maya_time_remaining_seconds"], int)
    assert ctx["maya_time_remaining_seconds"] > 0
    db.conn.close()


def test_context_pqc_verification_verified_after_fix(tmp_path):
    """Regression test for the action_detail/action_type mismatch bug
    described in this file's module docstring."""
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1595", "phase": "recon_active"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]

    ctx = gate.get_enriched_approval_context(payload_id)
    assert ctx["original_pqc_signature_verification"] == "verified"
    db.conn.close()


def test_context_verification_unavailable_when_no_pqc_entry(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1595", "phase": "recon_active"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    db.conn.execute("UPDATE approval_requests SET pqc_entry_id = NULL WHERE request_id = ?", (payload_id,))
    db.conn.commit()

    ctx = gate.get_enriched_approval_context(payload_id)
    assert ctx["original_pqc_signature_verification"] == "unavailable"
    db.conn.close()


def test_status_timeline_progresses_through_full_lifecycle(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    maya = staged[0]["maya_challenge"]

    stages_before = [s["stage"] for s in gate.get_enriched_approval_context(payload_id)["timeline"]]
    assert stages_before == ["staged", "challenge_issued"]

    gate.consume_maya_challenge(maya["session_id"], maya["challenge_token"], "lead")
    stages_mid = [s["stage"] for s in gate.get_enriched_approval_context(payload_id)["timeline"]]
    assert stages_mid == ["staged", "challenge_issued", "challenge_consumed"]

    gate.approve_payload(payload_id, "lead", "authorized")
    timeline = gate.get_enriched_approval_context(payload_id)["timeline"]
    stages_final = [s["stage"] for s in timeline]
    assert stages_final == ["staged", "challenge_issued", "challenge_consumed", "approved"]
    # every stage carries a real timestamp, and every stage but one has a
    # matched PQC entry_id (challenge_issued's is looked up separately)
    for stage in timeline:
        assert stage["timestamp"] is not None
        assert stage["pqc_entry_id"]
    db.conn.close()


def test_status_timeline_records_executed_stage(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1595", "phase": "recon_active"}],  # LOW risk -> no Maya gate
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    gate.approve_payload(payload_id, "lead", "authorized")
    result = gate.execute_staged_payload(payload_id)
    assert result["status"] == "executed"

    stages = [s["stage"] for s in gate.get_enriched_approval_context(payload_id)["timeline"]]
    assert stages[-1] == "executed_simulated"
    db.conn.close()


# ---------------------------------------------------------------------------
# verify_stored_entry() -- stateless re-verification against a row's OWN
# recorded public key/algorithm (not a live PQCAuditManager instance's key)
# ---------------------------------------------------------------------------

def test_verify_stored_entry_detects_tampered_signature(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1595", "phase": "recon_active"}],
        target="10.0.0.5", operator_id="op1",
    )
    entry_id = db.get_approval_request(staged[0]["payload_id"])["pqc_entry_id"]
    row = db.get_pqc_audit_entry(entry_id)
    assert verify_stored_entry(row) is True

    tampered = dict(row)
    tampered["pqc_signature"] = "00" * 32
    assert verify_stored_entry(tampered) is False
    db.conn.close()


def test_verify_stored_entry_survives_a_different_live_manager_instance(tmp_path):
    """The whole point: keys are per-process/per-instance and not
    persisted, so a freshly-constructed ExploitAgent (a new PQCAuditManager,
    a new keypair) must still be able to re-verify an entry signed by a
    DIFFERENT ExploitAgent/manager instance, because verification uses the
    row's own recorded public key -- not whatever key the checking
    instance happens to hold."""
    db = _authorized_db(tmp_path)
    gate1 = ExploitAgent(db_manager=db)
    staged = gate1.stage_payloads(
        [{"technique_id": "T1595", "phase": "recon_active"}],
        target="10.0.0.5", operator_id="op1",
    )
    entry_id = db.get_approval_request(staged[0]["payload_id"])["pqc_entry_id"]
    row = db.get_pqc_audit_entry(entry_id)

    gate2 = ExploitAgent(db_manager=db)  # fresh instance, different keypair
    assert gate2._get_pqc().public_key_hex != gate1._get_pqc().public_key_hex
    assert verify_stored_entry(row) is True  # verified from the row alone, no live-key dependency
    db.conn.close()
