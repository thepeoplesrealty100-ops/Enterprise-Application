"""
test_v22_modules.py — tests for v2.2 (AIP payload generator + Unified Security Fabric).
Run: cd backend && python -m pytest tests/test_v22_modules.py -q
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from database import DuckDBManager
from payloads.cheatsheet_ontology import CheatsheetOntology
from payloads.aip_payload_generator import AIPPayloadGenerator
from security_agents.unified_fabric import UnifiedSecurityFabric, FABRIC_CAPABILITIES
from tools.authorization import AuthorizationError


def _authorized_db():
    db = DuckDBManager(db_path=":memory:")
    now = datetime.now(timezone.utc)
    db.add_scope("ACME", "10.0.0.0/24, acme.example.org", now - timedelta(days=1), now + timedelta(days=30))
    db.add_insurance_policy("P1", "Lloyds", 1_000_000, now + timedelta(days=365))
    return db


# ── Cheatsheet ontology ────────────────────────────────────────────────────

def test_ontology_loads():
    o = CheatsheetOntology()
    assert o.loaded
    assert o.stats()["entries"] >= 50

def test_ontology_excludes_social_eng_from_executable():
    o = CheatsheetOntology()
    assert o.resolve(category="social-eng") == []          # executable path: excluded
    assert len(o.resolve(category="social-eng", include_non_executable=True)) >= 1  # reference: present

def test_ontology_resolves_commands_parameterized():
    o = CheatsheetOntology()
    cmds = o.resolve_commands("enumeration", target="10.0.0.9", limit_entries=5)
    assert len(cmds) > 0
    assert all("command" in c and "source_id" in c for c in cmds)


# ── AIP payload generator ──────────────────────────────────────────────────

def test_aip_generate_authorized():
    db = _authorized_db()
    aip = AIPPayloadGenerator(db=db)
    plan = aip.generate("10.0.0.5", "enumeration", "op1")
    assert plan["authorization"]["authorized"] is True
    assert plan["summary"]["total_payloads"] > 0
    assert plan["pqc_signature"]                 # PQC-signed
    assert db.count_pqc_entries() >= 2           # auth grant + plan signature

def test_aip_blocks_out_of_scope():
    db = _authorized_db()
    aip = AIPPayloadGenerator(db=db)
    try:
        aip.generate("8.8.8.8", "recon_active", "op1")
        assert False, "should have raised AuthorizationError"
    except AuthorizationError:
        pass

def test_aip_engagement_all_phases():
    db = _authorized_db()
    aip = AIPPayloadGenerator(db=db)
    eng = aip.generate_engagement("10.0.0.5", "op1")
    assert eng["summary"]["phase_count"] >= 5
    assert eng["summary"]["total_payloads"] > 0


# ── Unified Security Fabric ────────────────────────────────────────────────

def test_fabric_seeds_seven_capabilities():
    db = DuckDBManager(db_path=":memory:")
    fab = UnifiedSecurityFabric(db=db)
    st = fab.status()
    assert st["capability_count"] == 7
    assert len(FABRIC_CAPABILITIES) == 7

def test_fabric_posture_scoring():
    db = DuckDBManager(db_path=":memory:")
    fab = UnifiedSecurityFabric(db=db)
    p0 = fab.posture()["overall_score"]
    fab.set_maturity("dlp", "Optimal", "t")
    fab.set_maturity("sase", "Optimal", "t")
    p1 = fab.posture()["overall_score"]
    assert p1 > p0                                # raising maturity raises posture

def test_fabric_events_and_snapshot():
    db = DuckDBManager(db_path=":memory:")
    fab = UnifiedSecurityFabric(db=db)
    fab.set_status("mdr", "degraded", "t")
    assert len(fab.recent_events()) >= 1
    snap = fab.record_posture_snapshot("t")
    assert "overall_score" in snap
    assert len(db.list_posture_assessments()) == 1

def test_fabric_ontology_graph():
    db = DuckDBManager(db_path=":memory:")
    fab = UnifiedSecurityFabric(db=db)
    g = fab.ontology_graph()
    assert g["stats"]["capabilities"] == 7
    assert any(o["type"] == "ZTPillar" for o in g["objects"])


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
