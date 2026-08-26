"""
test_v23_modules.py — tests for v2.3 (wireless phase, WirelessAgent,
Human Approval Gate, and the v2.3 schema expansion).
Run: cd backend && python -m pytest tests/test_v23_modules.py -q
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from database import DuckDBManager
from payloads.payload_generator import PayloadGenerator
from payloads.aip_payload_generator import AIPPayloadGenerator
from security_agents.wireless_agent import WirelessAgent
from security_agents.exploit_agent import ExploitAgent
from tools.authorization import AuthorizationError


def _authorized_db():
    db = DuckDBManager(db_path=":memory:")
    now = datetime.now(timezone.utc)
    db.add_scope("ACME", "10.0.0.0/24, acme.example.org, wifi-hq-office",
                 now - timedelta(days=1), now + timedelta(days=30))
    db.add_insurance_policy("P1", "Lloyds", 1_000_000, now + timedelta(days=365))
    return db


# ── Wireless PayloadGenerator phase ─────────────────────────────────────────

def test_wireless_phase_returns_mitre_tagged_payloads():
    gen = PayloadGenerator()
    payloads = gen.generate_phase("wireless", "AA:BB:CC:DD:EE:FF")
    assert len(payloads) > 0
    assert all(p["phase"] == "wireless" for p in payloads)
    technique_ids = {p["technique_id"] for p in payloads}
    # Real MITRE ATT&CK technique IDs this phase should be tagging with.
    assert "T1669" in technique_ids           # Wi-Fi Networks
    assert "T1557.004" in technique_ids       # AiTM: Evil Twin
    assert "T1040" in technique_ids           # Network Sniffing
    assert any(t.startswith("T1110") for t in technique_ids)  # Brute Force family


def test_web_application_and_vulnerability_analysis_aliases_resolve():
    """Regression test for the phase-name mismatch bug: AIP's default
    engagement phases ("web_application", "vulnerability_analysis",
    "post_exploitation_assessment", "encryption_analysis") previously had
    no matching key in PayloadGenerator.generate_phase()'s dispatch map and
    silently produced zero MITRE payloads."""
    gen = PayloadGenerator()
    assert len(gen.generate_phase("web_application", "10.0.0.5")) > 0
    assert len(gen.generate_phase("vulnerability_analysis", "10.0.0.5")) > 0
    assert len(gen.generate_phase("post_exploitation_assessment", "10.0.0.5")) > 0
    assert len(gen.generate_phase("encryption_analysis", "10.0.0.5")) > 0


# ── AIP wireless integration (no more cheatsheet-only fallback) ────────────

def test_aip_wireless_no_longer_cheatsheet_only_fallback():
    db = _authorized_db()
    aip = AIPPayloadGenerator(db=db)
    plan = aip.generate("wifi-hq-office", "wireless", "op1")
    assert plan["authorization"]["authorized"] is True
    assert plan["summary"]["mitre_count"] > 0, "wireless phase must produce real MITRE payloads, not just cheatsheet fallback"
    assert plan["pqc_signature"]


def test_aip_high_risk_wireless_plan_auto_stages_approval():
    db = _authorized_db()
    aip = AIPPayloadGenerator(db=db)
    plan = aip.generate("wifi-hq-office", "wireless", "op1")
    assert plan["requires_human_approval"] is True   # deauth/evil-twin/WPS are HIGH risk
    assert plan["approval_request_id"] is not None
    row = db.get_approval_request(plan["approval_request_id"])
    assert row is not None
    assert row["status"] == "pending"


def test_aip_engagement_includes_wireless_by_default():
    db = _authorized_db()
    aip = AIPPayloadGenerator(db=db)
    eng = aip.generate_engagement("wifi-hq-office", "op1")
    assert "wireless" in eng["phases"]
    assert eng["phases"]["wireless"]["summary"]["mitre_count"] > 0


# ── WirelessAgent ────────────────────────────────────────────────────────

def test_wireless_agent_authorization_gate():
    db = _authorized_db()
    agent = WirelessAgent(db_manager=db)
    result = agent.scan("wifi-hq-office", operator_id="op1")
    assert result["phase"] == "CPENT-Phase-Wireless"
    assert "interfaces" in result
    assert "findings_summary" in result


def test_wireless_agent_blocks_out_of_scope():
    db = _authorized_db()
    agent = WirelessAgent(db_manager=db)
    try:
        agent.scan("not-in-scope-site", operator_id="op1")
        assert False, "should have raised AuthorizationError"
    except AuthorizationError:
        pass


# ── Human Approval Gate (ExploitAgent) ──────────────────────────────────────

def test_approval_gate_blocks_unapproved_execution():
    db = _authorized_db()
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads([{"technique_id": "T1110", "service": "ssh"}],
                                  target="10.0.0.5", operator_id="op1")
    assert len(staged) == 1
    payload_id = staged[0]["payload_id"]

    row = db.get_approval_request(payload_id)
    assert row["status"] == "pending"

    # Regression: execute must be BLOCKED before approval (the original bug
    # let anything through because it checked requires_approval, which is
    # always True, instead of the actual approval decision).
    result = gate.execute_staged_payload(payload_id)
    assert result["status"] == "blocked"


def test_approval_gate_allows_execution_after_approval():
    db = _authorized_db()
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads([{"technique_id": "T1595"}], target="10.0.0.5", operator_id="op1")
    payload_id = staged[0]["payload_id"]

    approval = gate.approve_payload(payload_id, "demo-lead", "authorized for scoped test")
    assert approval["status"] == "approved"
    assert db.get_approval_request(payload_id)["status"] == "approved"

    result = gate.execute_staged_payload(payload_id)
    assert result["status"] == "executed"


def test_approval_gate_denial_persists_as_audit_record():
    db = _authorized_db()
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads([{"technique_id": "T1190", "finding": "demo"}],
                                  target="10.0.0.5", operator_id="op1")
    payload_id = staged[0]["payload_id"]

    denial = gate.reject_payload(payload_id, "demo-lead", "out of scope for this engagement")
    assert denial["status"] == "rejected"

    # Row persists (denied), even though it's dropped from the in-process cache.
    row = db.get_approval_request(payload_id)
    assert row["status"] == "denied"
    assert payload_id not in [p["payload_id"] for p in gate.list_staged_payloads()]


# ── v2.3 schema ──────────────────────────────────────────────────────────

def test_operators_table_crud():
    db = DuckDBManager(db_path=":memory:")
    db.upsert_operator({"operator_id": "op1", "email": "op1@example.com", "role": "lead"})
    op = db.get_operator("op1")
    assert op["role"] == "lead"
    assert len(db.list_operators()) == 1


def test_attack_mappings_and_coverage_summary():
    db = DuckDBManager(db_path=":memory:")
    db.insert_attack_mapping({"tactic": "Discovery", "technique_id": "T1669", "technique_name": "Wi-Fi Networks"})
    db.insert_attack_mapping({"tactic": "Credential Access", "technique_id": "T1110", "technique_name": "Brute Force"})
    summary = db.attack_coverage_summary()
    assert summary["distinct_techniques"] == 2
    assert "Discovery" in summary["by_tactic"]


def test_compliance_checkpoint_hash_chain_detects_tamper():
    db = DuckDBManager(db_path=":memory:")
    db.insert_compliance_checkpoint({"action_type": "scan", "operator_id": "op1",
                                      "target": "10.0.0.5", "authorization_result": "granted"})
    db.insert_compliance_checkpoint({"action_type": "scan", "operator_id": "op1",
                                      "target": "10.0.0.6", "authorization_result": "granted"})
    verdict = db.verify_compliance_chain()
    assert verdict["valid"] is True
    assert verdict["checkpoints_verified"] == 2

    # Tamper with row 1's target directly and confirm the chain now fails.
    db.conn.execute("UPDATE compliance_checkpoints SET target = 'tampered' WHERE id = 1")
    db.conn.commit()
    verdict2 = db.verify_compliance_chain()
    assert verdict2["valid"] is False


def test_rfp_response_roundtrip():
    db = DuckDBManager(db_path=":memory:")
    db.insert_rfp_response({"client_name": "ACME", "methodology": "PTES", "tools_list": ["nmap"]})
    responses = db.list_rfp_responses()
    assert len(responses) == 1
    assert responses[0]["tools_list"] == ["nmap"]


def test_table_stats_includes_v23_tables():
    db = DuckDBManager(db_path=":memory:")
    stats = db.table_stats()
    for t in ("operators", "attack_mappings", "compliance_checkpoints",
              "rfp_responses", "approval_requests"):
        assert t in stats, f"missing v2.3 table in table_stats(): {t}"
        assert stats[t] == 0


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn(); passed += 1; print(f"  PASS  {fn.__name__}")
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e}"); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
