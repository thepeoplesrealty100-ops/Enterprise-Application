"""
test_v24_modules.py — tests for v2.4 (Horizon, Agentic Canvas, Resonance,
Q'AIP Energy Core + orbital comms).
Run: cd backend && python -m pytest tests/test_v24_modules.py -q
"""
import sys
import uuid
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from database import DuckDBManager
from llm_energy_core import EnergyCore


# ── Horizon ──────────────────────────────────────────────────────────────

def test_ai_safety_event_roundtrip_and_summary():
    db = DuckDBManager(db_path=":memory:")
    db.insert_ai_safety_event({"event_id": str(uuid.uuid4()), "client_id": "acme",
                                "soc_compliance_tier": "SOC2 Type II", "alert_severity": 5,
                                "regulatory_schema_status": "Attention Required"})
    db.insert_ai_safety_event({"event_id": str(uuid.uuid4()), "client_id": "acme",
                                "soc_compliance_tier": "HIPAA", "alert_severity": 2,
                                "regulatory_schema_status": "Resolved"})
    events = db.list_ai_safety_events(client_id="acme")
    assert len(events) == 2

    summary = db.horizon_regulatory_summary()
    assert summary["total_events"] == 2
    assert summary["by_regulatory_status"]["Attention Required"] == 1
    assert summary["compliance_gaps_by_tier"]["SOC2 Type II"] == 1


# ── Agentic Canvas (reuses the v2.3 Human Approval Gate) ────────────────

def test_canvas_patch_blocked_until_approved():
    db = DuckDBManager(db_path=":memory:")
    approval_id = str(uuid.uuid4())
    db.create_approval_request({"request_id": approval_id, "requested_by": "op1",
                                 "action_type": "agentic_canvas_patch_deploy",
                                 "target": "10.0.0.9", "risk_level": "HIGH"})
    task_id = str(uuid.uuid4())
    db.create_remediation_task({"task_id": task_id, "target_machine_ip": "10.0.0.9",
                                 "patch_id": "KB123", "approval_request_id": approval_id})

    # Not approved yet — must be blocked.
    result = db.advance_remediation_task(task_id, 50)
    assert result["status"] == "blocked"

    # Approve via the same v2.3 gate, then it must succeed.
    db.decide_approval_request(approval_id, "approved", "lead1", "looks fine")
    result2 = db.advance_remediation_task(task_id, 50)
    assert result2["deployment_progress"] == 50
    assert result2["operator_approval_status"] == "approved"


def test_canvas_task_completes_at_100():
    db = DuckDBManager(db_path=":memory:")
    approval_id = str(uuid.uuid4())
    db.create_approval_request({"request_id": approval_id, "requested_by": "op1", "action_type": "x"})
    db.decide_approval_request(approval_id, "approved", "lead1")
    task_id = str(uuid.uuid4())
    db.create_remediation_task({"task_id": task_id, "approval_request_id": approval_id})
    result = db.advance_remediation_task(task_id, 100)
    assert result["remediation_status"] == "completed"


# ── Resonance / Global Dashboard ─────────────────────────────────────────

def test_fleet_matrix_upsert_and_quarantine_filter():
    db = DuckDBManager(db_path=":memory:")
    db.upsert_fleet_host({"machine_id": "m1", "predictive_threat_score": 0.9, "is_quarantined": True})
    db.upsert_fleet_host({"machine_id": "m2", "predictive_threat_score": 0.1, "is_quarantined": False})
    all_hosts = db.list_fleet_matrix()
    assert len(all_hosts) == 2
    quarantined = db.list_fleet_matrix(quarantined_only=True)
    assert len(quarantined) == 1
    assert quarantined[0]["machine_id"] == "m1"


def test_resonance_settings_derived_from_real_tables_not_editable_blob():
    db = DuckDBManager(db_path=":memory:")
    db.upsert_operator({"operator_id": "op1", "role": "admin"})
    snap = db.resonance_settings_snapshot(str(uuid.uuid4()))
    assert snap["api_encryption_standard"] == "ML-DSA-65 + AES-256-GCM"
    assert snap["rbac_policy_hash"]  # derived, non-empty
    latest = db.latest_security_settings()
    assert latest["config_id"] == snap["config_id"]


# ── Q'AIP Energy Core + orbital comms ────────────────────────────────────

def test_energy_core_throttles_after_burst_capacity_exhausted():
    core = EnergyCore(requests_per_minute=60, burst_capacity=3)
    results = [core.allow() for _ in range(5)]
    assert results[:3] == [True, True, True]
    assert results[3] is False and results[4] is False
    status = core.status()
    assert status["allowed_count"] == 3
    assert status["throttled_count"] == 2


def test_orbital_comms_log_and_stats():
    db = DuckDBManager(db_path=":memory:")
    db.log_orbital_comm({"comm_id": str(uuid.uuid4()), "event_type": "aip_prioritization",
                          "computational_agent_id": "aip-llm-prioritizer", "execution_latency_ms": 120})
    db.log_orbital_comm({"comm_id": str(uuid.uuid4()), "event_type": "aip_prioritization",
                          "computational_agent_id": "aip-llm-prioritizer", "execution_latency_ms": 80})
    stats = db.orbital_comms_stats()
    assert stats["total"] == 2
    assert stats["avg_latency_ms"] == 100.0
    assert stats["by_event_type"]["aip_prioritization"] == 2


def test_table_stats_includes_v24_tables():
    db = DuckDBManager(db_path=":memory:")
    stats = db.table_stats()
    for t in ("ai_safety_events", "agentic_remediation_tasks", "global_fleet_matrix",
              "global_security_settings", "quantum_orbital_comms"):
        assert t in stats, f"missing v2.4 table in table_stats(): {t}"
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
