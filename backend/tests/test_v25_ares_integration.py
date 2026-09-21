"""
test_v25_ares_integration.py — tests for v2.5 (Ares Unified Control Plane).
Run: cd backend && python -m pytest tests/test_v25_ares_integration.py -q

Style note: like test_v22/v23/v24_modules.py, these talk to DuckDBManager
directly rather than going through FastAPI's TestClient. That's deliberate
here specifically: routers/*.py each instantiate their own module-level
DuckDBManager() against the default "jakal.duckdb" file path, so a
TestClient-driven HTTP test would exercise (and mutate) that shared,
persistent, gitignored file rather than an isolated :memory: database --
same risk the rest of this test suite already avoids. The "simulate a test
cycle" scenario below (ingest -> score -> Horizon flag -> Global Matrix
update) is reproduced by driving the same database.py methods the routers
call, in the same order, against an isolated :memory: instance. It was
also verified once, live, over real HTTP via TestClient against the actual
app during development -- see the delivery notes for that transcript.
"""
import sys
import uuid
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from database import DuckDBManager, WIRED_SECURITY_AGENTS
from threat_scoring import score_recon_finding
from security_agents.exploit_agent import ExploitAgent


# ── threat_scoring — pure function, no DB ────────────────────────────────

def test_scoring_critical_keyword_crosses_hitl_threshold():
    score = score_recon_finding({
        "threat_category": "EXPOSED_SERVICE",
        "finding_summary": "Unauthenticated RCE on exposed management port",
    })
    assert score > 0.8


def test_scoring_explicit_cvss_hint_honored():
    score = score_recon_finding({
        "threat_category": "EXPOSED_SERVICE",
        "finding_summary": "generic finding",
        "indicators": {"cvss_score": 9.8},
    })
    assert score == 0.98


def test_scoring_unclassified_finding_gets_low_nonzero_floor():
    score = score_recon_finding({})
    assert 0.0 < score < 0.3


def test_scoring_category_floor_applies_with_empty_summary():
    # threat_category text is itself scanned for keywords (by design -- see
    # threat_scoring.py's docstring), and "shadow_ai" is also a _HIGH_KEYWORDS
    # entry (0.7), which is stricter than SHADOW_AI's own category floor
    # (0.5) -- max() correctly takes the stricter signal. Use a category
    # with no keyword-table collision to isolate the floor itself.
    score = score_recon_finding({"threat_category": "SHADOW_AI", "finding_summary": ""})
    assert score == 0.7

    floor_only = score_recon_finding({"threat_category": "SOC2_VIOLATION", "finding_summary": ""})
    assert floor_only == 0.55


def test_scoring_bounded_0_to_1():
    score = score_recon_finding({
        "threat_category": "RANSOMWARE",
        "finding_summary": "ransomware zero-day critical exploited in the wild",
        "indicators": {"cvss_score": 10, "severity_hint": 1.0},
    })
    assert 0.0 <= score <= 1.0


# ── unified_security_events ───────────────────────────────────────────────

def test_unified_security_event_roundtrip():
    db = DuckDBManager(db_path=":memory:")
    eid = str(uuid.uuid4())
    db.insert_unified_security_event({
        "event_id": eid, "source_module": "GOD_S_EYE_RECON",
        "threat_category": "EXPOSED_SERVICE", "severity_score": 0.95,
        "raw_payload": {"target": "10.0.0.5"},
    })
    events = db.list_unified_security_events(source_module="GOD_S_EYE_RECON")
    assert len(events) == 1
    assert events[0]["event_id"] == eid
    assert events[0]["raw_payload"]["target"] == "10.0.0.5"

    stats = db.unified_security_events_stats()
    assert stats["total"] == 1
    assert stats["threats_blocked_count"] == 1  # severity >= 0.5


def test_link_unified_event_approval():
    db = DuckDBManager(db_path=":memory:")
    eid = str(uuid.uuid4())
    db.insert_unified_security_event({"event_id": eid, "source_module": "HORIZON"})
    ok = db.link_unified_event_approval(eid, "some-approval-id")
    assert ok
    events = db.list_unified_security_events()
    assert events[0]["approval_request_id"] == "some-approval-id"


# ── origin_module folded into approval_requests.payload_detail ───────────

def test_approval_request_origin_module_stored_in_payload_detail_not_a_column():
    """
    origin_module deliberately isn't a real approval_requests column (see
    database.py's v2.5 CREATE TABLE comment) -- confirm it round-trips
    through payload_detail instead, and that create_approval_request still
    works with no origin_module at all (existing v2.3/v2.4 callers).
    """
    db = DuckDBManager(db_path=":memory:")
    rid = str(uuid.uuid4())
    db.create_approval_request({
        "request_id": rid, "requested_by": "qaip-recon-scorer",
        "action_type": "qaip_recon_high_severity_response",
        "origin_module": "GOD_S_EYE_RECON",
        "payload_detail": {"target": "10.0.0.5"},
    })
    fetched = db.get_approval_request(rid)
    assert fetched["payload_detail"]["origin_module"] == "GOD_S_EYE_RECON"
    assert fetched["payload_detail"]["target"] == "10.0.0.5"

    # No origin_module column exists on the table itself.
    cols = {d[0] for d in db.conn.execute("DESCRIBE approval_requests").fetchall()}
    assert "origin_module" not in cols

    # Backward compatible: existing callers that never pass origin_module
    # still work exactly as before.
    rid2 = str(uuid.uuid4())
    db.create_approval_request({"request_id": rid2, "requested_by": "op1", "action_type": "x"})
    fetched2 = db.get_approval_request(rid2)
    assert "origin_module" not in fetched2["payload_detail"]


# ── horizon_trust_fabric snapshot (derived, not independently writable) ──

def test_horizon_trust_fabric_snapshot_derives_from_real_tables():
    db = DuckDBManager(db_path=":memory:")

    # Fabric health: one active module -> SECURE.
    db.upsert_fabric_module({"module_key": "mdr", "label": "MDR", "pillar": "Data", "status": "active"})

    # Horizon compliance: 1 of 2 events needs attention -> 50% coverage.
    db.insert_ai_safety_event({"event_id": str(uuid.uuid4()), "client_id": "acme",
                                "regulatory_schema_status": "Attention Required"})
    db.insert_ai_safety_event({"event_id": str(uuid.uuid4()), "client_id": "acme",
                                "regulatory_schema_status": "Resolved"})

    # Unified bus: one Shadow AI hit, one DLP match, one still-open critical.
    db.insert_unified_security_event({"event_id": str(uuid.uuid4()), "source_module": "HORIZON",
                                       "threat_category": "SHADOW_AI", "severity_score": 0.7})
    db.insert_unified_security_event({"event_id": str(uuid.uuid4()), "source_module": "HORIZON",
                                       "threat_category": "DLP_MATCH", "severity_score": 0.6})
    db.insert_unified_security_event({"event_id": str(uuid.uuid4()), "source_module": "GOD_S_EYE_RECON",
                                       "threat_category": "EXPOSED_SERVICE", "severity_score": 0.95})

    snap = db.horizon_trust_fabric_snapshot(str(uuid.uuid4()))
    assert snap["fabric_status"] == "SECURE"
    assert snap["compliance_coverage_pct"] == 50.0
    assert snap["active_agent_count"] == len(WIRED_SECURITY_AGENTS) == 6
    assert snap["threats_blocked_count"] == 3  # all 3 events >= 0.5
    assert snap["shadow_ai_status"] == "DETECTED"
    assert snap["soc2_compliance_status"] == "ATTENTION_REQUIRED"
    assert snap["dlp_status"] == "MATCHES_DETECTED"
    # The 0.95 event has no approval_request_id yet -> still an open threat.
    assert snap["adversarial_defense_status"] == "ACTIVE_THREATS_DETECTED"


def test_horizon_trust_fabric_adversarial_status_clears_once_approved():
    db = DuckDBManager(db_path=":memory:")
    eid = str(uuid.uuid4())
    db.insert_unified_security_event({"event_id": eid, "source_module": "GOD_S_EYE_RECON",
                                       "threat_category": "EXPOSED_SERVICE", "severity_score": 0.9})
    snap1 = db.horizon_trust_fabric_snapshot(str(uuid.uuid4()))
    assert snap1["adversarial_defense_status"] == "ACTIVE_THREATS_DETECTED"

    rid = str(uuid.uuid4())
    db.create_approval_request({"request_id": rid, "requested_by": "op1", "action_type": "x"})
    db.link_unified_event_approval(eid, rid)

    snap2 = db.horizon_trust_fabric_snapshot(str(uuid.uuid4()))
    assert snap2["adversarial_defense_status"] == "NOMINAL"


def test_horizon_trust_fabric_uninitialized_when_no_fabric_modules_seeded():
    db = DuckDBManager(db_path=":memory:")
    snap = db.horizon_trust_fabric_snapshot(str(uuid.uuid4()))
    assert snap["fabric_status"] == "UNINITIALIZED"


def test_horizon_trust_fabric_degraded_when_a_module_is_down():
    db = DuckDBManager(db_path=":memory:")
    db.upsert_fabric_module({"module_key": "mdr", "label": "MDR", "pillar": "Data", "status": "active"})
    db.upsert_fabric_module({"module_key": "dlp", "label": "DLP", "pillar": "Data", "status": "degraded"})
    snap = db.horizon_trust_fabric_snapshot(str(uuid.uuid4()))
    assert snap["fabric_status"] == "DEGRADED"


def test_latest_horizon_trust_fabric_returns_most_recent():
    db = DuckDBManager(db_path=":memory:")
    db.horizon_trust_fabric_snapshot(str(uuid.uuid4()))
    second_id = str(uuid.uuid4())
    db.horizon_trust_fabric_snapshot(second_id)
    latest = db.latest_horizon_trust_fabric()
    assert latest["fabric_id"] == second_id


# ── full simulated cycle: ingest -> score -> Horizon flags -> Global Matrix ─

def test_simulated_ares_cycle_exposed_service_to_global_matrix():
    """
    Mirrors POST /api/qaip/ingest-recon-intel's exact logic (score, log to
    the bus, stage approval if over threshold) followed by
    GET /api/ares/global-matrix-summary, driven directly against the DB
    layer -- see module docstring for why this isn't a TestClient test.
    """
    db = DuckDBManager(db_path=":memory:")
    db.upsert_fabric_module({"module_key": "mdr", "label": "MDR", "pillar": "Data", "status": "active"})

    payload = {
        "source_module": "GOD_S_EYE_RECON", "target": "203.0.113.9",
        "threat_category": "EXPOSED_SERVICE",
        "finding_summary": "Exposed RDP with default credentials",
        "indicators": {},
    }
    severity = score_recon_finding(payload)
    assert severity > 0.5  # "default credentials" keyword

    event_id = str(uuid.uuid4())
    db.insert_unified_security_event({
        "event_id": event_id, "source_module": payload["source_module"],
        "threat_category": payload["threat_category"], "severity_score": severity,
        "raw_payload": payload,
    })

    approval_request_id = None
    if severity > 0.8:
        approval_request_id = str(uuid.uuid4())
        db.create_approval_request({
            "request_id": approval_request_id, "requested_by": "system",
            "action_type": "qaip_recon_high_severity_response",
            "target": payload["target"], "risk_level": "CRITICAL",
            "origin_module": payload["source_module"], "payload_detail": payload,
        })
        db.link_unified_event_approval(event_id, approval_request_id)

    matrix = db.horizon_trust_fabric_snapshot(str(uuid.uuid4()))
    assert matrix["fabric_status"] == "SECURE"
    assert matrix["threats_blocked_count"] == 1
    events = db.list_unified_security_events()
    assert events[0]["event_id"] == event_id
    assert events[0]["severity_score"] == severity
    if approval_request_id:
        assert events[0]["approval_request_id"] == approval_request_id


# ── ExploitAgent: DB is the source of truth, not just its in-memory cache ─
#
# Found while building v2.5: ExploitAgent.approve_payload/reject_payload/
# execute_staged_payload all required payload_id to already be in
# self.staged_payloads, an in-process dict populated ONLY by
# stage_payloads(). Agentic Canvas's deploy_patch (v2.4) and Ares/Q'AIP's
# ingest-recon-intel (v2.5) both write approval_requests rows directly via
# database.py, bypassing that cache entirely -- so a Canvas- or Ares-
# originated request could never actually be approved/executed through
# POST /api/approval/{id}/approve|deny|execute, even though Canvas's own
# deploy_patch response explicitly tells callers to approve there. Existing
# tests never caught this because they call db.decide_approval_request()
# directly instead of going through ExploitAgent/the approval router.

def test_exploit_agent_approves_a_request_it_never_staged():
    db = DuckDBManager(db_path=":memory:")
    gate = ExploitAgent(db_manager=db)

    request_id = str(uuid.uuid4())
    db.create_approval_request({
        "request_id": request_id, "requested_by": "qaip-recon-scorer",
        "action_type": "qaip_recon_high_severity_response", "risk_level": "CRITICAL",
    })
    assert request_id not in gate.staged_payloads  # never staged via this agent

    result = gate.approve_payload(request_id, "op1", "looks legit")
    assert result["status"] == "approved"
    assert db.get_approval_request(request_id)["status"] == "approved"


def test_exploit_agent_executes_a_db_only_approved_request():
    db = DuckDBManager(db_path=":memory:")
    gate = ExploitAgent(db_manager=db)

    request_id = str(uuid.uuid4())
    db.create_approval_request({
        "request_id": request_id, "requested_by": "system", "action_type": "agentic_canvas_patch_deploy",
        "payload_detail": {"technique": "T1595", "impact": "patch rollout"},
    })
    blocked = gate.execute_staged_payload(request_id)
    assert blocked["status"] == "blocked"

    db.decide_approval_request(request_id, "approved", "lead1")
    executed = gate.execute_staged_payload(request_id)
    assert executed["status"] == "executed"
    assert executed["technique"] == "T1595"  # pulled from payload_detail, not the in-memory cache


def test_exploit_agent_rejects_a_request_it_never_staged_without_keyerror():
    db = DuckDBManager(db_path=":memory:")
    gate = ExploitAgent(db_manager=db)

    request_id = str(uuid.uuid4())
    db.create_approval_request({"request_id": request_id, "requested_by": "system", "action_type": "x"})
    result = gate.reject_payload(request_id, "op1", "no")
    assert result["status"] == "rejected"
    assert db.get_approval_request(request_id)["status"] == "denied"


def test_exploit_agent_still_reports_unknown_payload_as_not_found():
    db = DuckDBManager(db_path=":memory:")
    gate = ExploitAgent(db_manager=db)
    result = gate.approve_payload("does-not-exist", "op1")
    assert result["status"] == "error"


# ── decide_approval_request / expire_* return values (the rowcount fix) ──

def test_decide_approval_request_returns_true_on_real_match():
    db = DuckDBManager(db_path=":memory:")
    rid = str(uuid.uuid4())
    db.create_approval_request({"request_id": rid, "requested_by": "op1", "action_type": "x"})
    assert db.decide_approval_request(rid, "approved", "lead1") is True
    # Already decided -- WHERE status='pending' no longer matches.
    assert db.decide_approval_request(rid, "approved", "lead1") is False


def test_decide_approval_request_returns_false_for_unknown_id():
    db = DuckDBManager(db_path=":memory:")
    assert db.decide_approval_request("nope", "approved", "lead1") is False


def test_rotate_and_revoke_encryption_key_return_values():
    """
    Same rowcount bug, same fix, in the (pre-existing, v2.1) encryption-key
    registry -- routers/crypto.py's POST /crypto/keys/rotate and /revoke
    both used to 404 on every call, even against a real, existing key_id,
    because rotate_encryption_key()/revoke_encryption_key() always returned
    False. Separately noted for the operator: register_encryption_key() has
    no callers anywhere in the app today, so encryption_keys stays empty in
    normal operation regardless of this fix -- that's a real, pre-existing
    gap (nothing currently persists a key when /crypto/encrypt generates
    one), flagged here rather than fixed, since wiring it up means deciding
    how EncryptionManager should look keys back up by id for /decrypt --
    a design decision, not a one-line bug fix.
    """
    db = DuckDBManager(db_path=":memory:")
    db.register_encryption_key({"key_id": "k1", "algorithm": "AES-256-GCM",
                                 "key_purpose": "payload", "operator_id": "op1"})
    assert db.rotate_encryption_key("k1") is True
    assert db.rotate_encryption_key("does-not-exist") is False

    db.register_encryption_key({"key_id": "k2", "algorithm": "AES-256-GCM",
                                 "key_purpose": "payload", "operator_id": "op1"})
    assert db.revoke_encryption_key("k2") is True
    assert db.revoke_encryption_key("does-not-exist") is False


# ── table_stats ────────────────────────────────────────────────────────

def test_table_stats_includes_v25_tables():
    db = DuckDBManager(db_path=":memory:")
    stats = db.table_stats()
    for t in ("unified_security_events", "horizon_trust_fabric"):
        assert t in stats, f"missing v2.5 table in table_stats(): {t}"
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
