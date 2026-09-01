"""
backend/tests/test_maya_ontology.py
JAKAL v3.0 — Ontology Engine (Palantir-style Object/Link digital twin) +
Maya-Vigesimal calendar 2FA challenge, interlocked with the existing
Human Approval Gate for HIGH/CRITICAL staged payloads.

Run: cd backend && python -m pytest tests/test_maya_ontology.py -q

Several of these tests specifically guard against real bugs found and
fixed while building this feature (all reproduced empirically before
being fixed -- see database.py's v3.0 schema comment and
consume_maya_session()'s docstring for the full writeups):

  - test_update_confidence_on_linked_node: this DuckDB version has a
    confirmed bug where UPDATE against a table with ANY secondary index
    raises a spurious "duplicate primary key" error, regardless of which
    column is indexed or updated. ontological_object_nodes and
    maya_vigesimal_auth_sessions (both UPDATEd by this feature) were built
    with no secondary indexes specifically to avoid it.
  - test_maya_session_retry_after_wrong_token: this feature's own
    original spec had consume_maya_session() permanently mark a session
    'denied' on ANY wrong-token attempt -- which made that same spec's own
    lifecycle test (submit a wrong token, then the correct one, on the
    same session) impossible to pass. Fixed to allow retry until expiry.
  - test_link_nonexistent_node_raises: FOREIGN KEY REFERENCES were tried
    first and reverted after two separate confirmed DuckDB bugs (creating
    a secondary index before an FK-referencing table exists; UPDATE on
    any referenced row's column being blocked entirely). Referential
    integrity is enforced at the application layer instead.
"""

import sys
import uuid
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from database import DuckDBManager
from services.ontology_engine import OntologyEngine
from security_agents.exploit_agent import ExploitAgent


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test_v3.duckdb")
    manager = DuckDBManager(db_path=path)
    yield manager
    manager.conn.close()


# ---------------------------------------------------------------------------
# Maya-Vigesimal calendar math
# ---------------------------------------------------------------------------

def test_vigesimal_math_roundtrip(db):
    agent = ExploitAgent(db_manager=db)
    day = agent._day_number()
    tz = agent._compute_tzolkin(day)
    ha = agent._compute_haab(day)
    assert "-" in tz and tz.split("-")[0].isdigit()
    assert 1 <= int(tz.split("-")[0]) <= 13
    assert "-" in ha


def test_vigesimal_calendar_round_cycle():
    """LCM(13x20, 365) = 18,980 days -- the Calendar Round: the same
    Tzolkin+Haab pair recurs only every 18,980 days, and day 0 must equal
    day 18,980 exactly (confirms the modular arithmetic is correct)."""
    agent = ExploitAgent(db_manager=None)
    assert (agent._compute_tzolkin(0), agent._compute_haab(0)) == \
           (agent._compute_tzolkin(18980), agent._compute_haab(18980))
    # and NOT equal at any smaller multiple that isn't a true common cycle
    assert (agent._compute_tzolkin(0), agent._compute_haab(0)) != \
           (agent._compute_tzolkin(260), agent._compute_haab(260))


def test_vigesimal_token_deterministic_and_payload_scoped():
    agent = ExploitAgent(db_manager=None)
    day = agent._day_number()
    tz, ha = agent._compute_tzolkin(day), agent._compute_haab(day)
    t1 = agent._vigesimal_challenge_token(tz, ha, "payload-a")
    t2 = agent._vigesimal_challenge_token(tz, ha, "payload-a")
    t3 = agent._vigesimal_challenge_token(tz, ha, "payload-b")
    assert t1 == t2  # deterministic for the same day + payload
    assert t1 != t3  # scoped to the specific payload
    assert len(t1) == 16
    assert set(t1) <= set("0123456789ABCDEFGHIJKLMNOP")


# ---------------------------------------------------------------------------
# Ontology Engine
# ---------------------------------------------------------------------------

def test_create_and_link_nodes(db):
    engine = OntologyEngine(db)
    n1 = engine.create_node("Asset", {"ip": "10.0.0.1"}, confidence=0.95)
    n2 = engine.create_node("Finding", {"cve": "CVE-2024-1234"})
    tid = engine.link_nodes(n1, n2, "AFFECTS", {"score": 0.9})
    assert tid
    sub = engine.query_subgraph(n1, max_depth=1)
    assert n1 in sub["nodes"]
    assert n2 in sub["nodes"]
    assert len(sub["edges"]) == 1


def test_update_confidence_on_linked_node(db):
    """Regression test: updating a node that IS referenced by an edge
    must succeed. See module docstring for the DuckDB bug this guards."""
    engine = OntologyEngine(db)
    n1 = engine.create_node("Asset", {"ip": "10.0.0.1"})
    n2 = engine.create_node("Finding", {})
    engine.link_nodes(n1, n2, "AFFECTS", {})
    ok = engine.update_confidence(n1, 0.42)
    assert ok is True
    assert engine.get_node(n1)["confidence_score"] == 0.42


def test_update_confidence_nonexistent_node(db):
    engine = OntologyEngine(db)
    assert engine.update_confidence(str(uuid.uuid4()), 0.5) is False


def test_link_nonexistent_node_raises(db):
    engine = OntologyEngine(db)
    with pytest.raises(ValueError):
        engine.link_nodes("nonexistent", "alsononexistent", "TEST", {})


def test_confidence_check_constraint_enforced(db):
    with pytest.raises(Exception):
        db.create_ontological_node("Asset", {}, confidence=5.0)  # out of [0,1]


def test_concurrent_node_creation(db):
    import concurrent.futures
    engine = OntologyEngine(db)

    def create_one(i):
        return engine.create_node("Test", {"i": i})

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(create_one, range(8)))
    assert len(set(results)) == 8


# ---------------------------------------------------------------------------
# Maya session lifecycle
# ---------------------------------------------------------------------------

def test_maya_session_lifecycle(db):
    agent = ExploitAgent(db_manager=db)
    payload_id = str(uuid.uuid4())
    challenge = agent._maya_vigesimal_challenge(payload_id, "op1", "CRITICAL")
    assert challenge["status"] == "pending"

    reuse_after_consume = db.consume_maya_session(
        challenge["session_id"], challenge["challenge_token"], "op1"
    )
    assert reuse_after_consume["status"] == "consumed"

    reuse = db.consume_maya_session(challenge["session_id"], challenge["challenge_token"], "op1")
    assert reuse["status"] == "error"


def test_maya_session_retry_after_wrong_token(db):
    """See module docstring: a wrong token must NOT permanently burn the
    session -- the operator can retry with the correct token afterward."""
    agent = ExploitAgent(db_manager=db)
    payload_id = str(uuid.uuid4())
    challenge = agent._maya_vigesimal_challenge(payload_id, "op1", "HIGH")

    bad = db.consume_maya_session(challenge["session_id"], "WRONG", "op1")
    assert bad["status"] == "error"

    good = db.consume_maya_session(challenge["session_id"], challenge["challenge_token"], "op1")
    assert good["status"] == "consumed"


def test_maya_session_not_found(db):
    result = db.consume_maya_session(str(uuid.uuid4()), "anything", "op1")
    assert result["status"] == "error"
    assert "not found" in result["message"]


def test_maya_session_expired(db):
    from datetime import datetime, timezone, timedelta
    sid = db.create_maya_session(
        "payload-x", "op1", "5-Ik", "9-Pop", "TOKEN2",
        datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    result = db.consume_maya_session(sid, "TOKEN2", "op1")
    assert result["status"] == "error"
    assert "expired" in result["message"]


def test_maya_session_never_created_for_low_medium_risk(db):
    agent = ExploitAgent(db_manager=db)
    assert agent._maya_vigesimal_challenge(str(uuid.uuid4()), "op1", "LOW") is None
    assert agent._maya_vigesimal_challenge(str(uuid.uuid4()), "op1", "MEDIUM") is None


def test_stage_payloads_attaches_maya_challenge_for_high_risk_only(db):
    agent = ExploitAgent(db_manager=db)
    staged = agent.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],  # -> severity: high
        target="10.0.0.5", operator_id="op1",
    )
    assert len(staged) == 1
    assert "maya_challenge" in staged[0]
    assert staged[0]["maya_challenge"]["status"] == "pending"

    low_staged = agent.stage_payloads(
        [{"technique_id": "T1595", "phase": "recon_active"}],  # -> severity: low
        target="10.0.0.5", operator_id="op1",
    )
    assert len(low_staged) == 1
    assert "maya_challenge" not in low_staged[0]


def test_maya_challenge_hides_raw_calendar_values(db):
    """The challenge handed back to callers (and, through them, the
    frontend) must expose only friendly display timestamps + session_id +
    challenge_token -- never the raw Tzolkin/Haab coordinates or the raw
    expires_at. The coordinates still live in the DB row (internal)."""
    agent = ExploitAgent(db_manager=db)
    payload_id = str(uuid.uuid4())
    challenge = agent._maya_vigesimal_challenge(payload_id, "op1", "CRITICAL")

    assert set(challenge.keys()) == {
        "session_id", "challenge_token", "display_issued_at", "display_expires_at", "status",
    }
    assert "tzolkin_coordinate" not in challenge
    assert "haab_coordinate" not in challenge
    assert "expires_at" not in challenge

    session = db.get_maya_session(challenge["session_id"])
    assert session["tzolkin_coordinate"]
    assert session["haab_coordinate"]
    # DB columns are TIMESTAMPTZ (real datetimes); the challenge dict holds
    # their friendly isoformat() string form for the frontend.
    assert session["display_issued_at"].isoformat() == challenge["display_issued_at"]
    assert session["display_expires_at"].isoformat() == challenge["display_expires_at"]


# ---------------------------------------------------------------------------
# Maya-Vigesimal interlock with the Human Approval Gate
# ---------------------------------------------------------------------------

def _authorized_db(tmp_path, name="test_v3_interlock.duckdb"):
    from datetime import datetime, timezone, timedelta
    path = str(tmp_path / name)
    manager = DuckDBManager(db_path=path)
    now = datetime.now(timezone.utc)
    manager.add_scope("ACME", "10.0.0.0/24, acme.example.org",
                       now - timedelta(days=1), now + timedelta(days=30))
    manager.add_insurance_policy("P1", "Lloyds", 1_000_000, now + timedelta(days=365))
    return manager


def test_approve_payload_blocked_while_maya_pending(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],  # -> HIGH -> Maya challenge
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    assert "maya_challenge" in staged[0]

    result = gate.approve_payload(payload_id, "demo-lead", "authorized")
    assert result["status"] == "error"
    assert db.get_approval_request(payload_id)["status"] == "pending"  # decision never recorded
    db.conn.close()


def test_reject_payload_blocked_while_maya_pending(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1190", "finding": "demo"}],  # -> CRITICAL -> Maya challenge
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]

    result = gate.reject_payload(payload_id, "demo-lead", "out of scope")
    assert result["status"] == "error"
    assert db.get_approval_request(payload_id)["status"] == "pending"
    db.conn.close()


def test_approve_payload_succeeds_only_after_maya_consumed(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    maya = staged[0]["maya_challenge"]

    blocked = gate.approve_payload(payload_id, "demo-lead", "authorized")
    assert blocked["status"] == "error"

    consumed = db.consume_maya_session(maya["session_id"], maya["challenge_token"], "demo-lead")
    assert consumed["status"] == "consumed"

    approved = gate.approve_payload(payload_id, "demo-lead", "authorized")
    assert approved["status"] == "approved"
    assert db.get_approval_request(payload_id)["status"] == "approved"
    db.conn.close()


def test_reject_payload_succeeds_only_after_maya_consumed(tmp_path):
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1190", "finding": "demo"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    maya = staged[0]["maya_challenge"]

    consumed = db.consume_maya_session(maya["session_id"], maya["challenge_token"], "demo-lead")
    assert consumed["status"] == "consumed"

    rejected = gate.reject_payload(payload_id, "demo-lead", "out of scope")
    assert rejected["status"] == "rejected"
    assert db.get_approval_request(payload_id)["status"] == "denied"
    db.conn.close()


def test_approve_payload_signed_audit_entry_includes_maya_session_id(tmp_path):
    """The PQC-signed audit entry for the approval decision must include
    maya_session_id so the calendar 2FA is traceable in the tamper-evident
    audit log, not just enforced at decision time."""
    import json
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1110", "phase": "credential_access"}],
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    maya = staged[0]["maya_challenge"]
    db.consume_maya_session(maya["session_id"], maya["challenge_token"], "demo-lead")

    approved = gate.approve_payload(payload_id, "demo-lead", "authorized")
    assert approved["status"] == "approved"

    rows = db.conn.execute(
        "SELECT action_detail FROM pqc_audit_log WHERE action_type = 'exploit_approval_granted' "
        "ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    assert rows is not None
    detail = json.loads(rows[0])
    assert detail["maya_session_id"] == maya["session_id"]
    db.conn.close()


def test_approve_payload_without_maya_session_proceeds_unimpeded(tmp_path):
    """LOW/MEDIUM-risk payloads never get a Maya challenge; the interlock
    must not invent a requirement that was never staged."""
    db = _authorized_db(tmp_path)
    gate = ExploitAgent(db_manager=db)
    staged = gate.stage_payloads(
        [{"technique_id": "T1595", "phase": "recon_active"}],  # -> LOW -> no Maya challenge
        target="10.0.0.5", operator_id="op1",
    )
    payload_id = staged[0]["payload_id"]
    assert "maya_challenge" not in staged[0]

    approved = gate.approve_payload(payload_id, "demo-lead", "authorized")
    assert approved["status"] == "approved"
    db.conn.close()


# ---------------------------------------------------------------------------
# Resonance policy enforcements + Q'AIP inference registry
# ---------------------------------------------------------------------------

def test_policy_crud(db):
    pid = db.upsert_resonance_policy("exploit_agent", "stage_exploit", 0.85, "require_approval")
    policies = db.list_active_policies("exploit_agent")
    assert any(p["policy_id"] == pid for p in policies)

    all_policies = db.list_active_policies()
    assert any(p["policy_id"] == pid for p in all_policies)


def test_qaip_registry(db):
    iid = db.register_qaip_inference(
        "grover",
        {"shots": 1024, "fidelity": 0.97},
        pqc_signature="deadbeef",
        operator_id="op1",
    )
    assert iid


def test_qaip_registry_related_node_integrity(db):
    engine = OntologyEngine(db)
    n1 = engine.create_node("Asset", {})
    iid = db.register_qaip_inference(
        "grover", {"shots": 512}, pqc_signature="abc", related_node_id=n1
    )
    assert iid

    with pytest.raises(ValueError):
        db.register_qaip_inference(
            "grover", {}, pqc_signature="x", related_node_id="nonexistent"
        )
