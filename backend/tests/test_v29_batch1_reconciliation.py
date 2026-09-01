"""
backend/tests/test_v29_batch1_reconciliation.py
JAKAL v2.9 — reconciliation of this branch's v2.6-v2.8 work with "Batch 1"
(core/enforcement.py, core/webhook_dispatcher.py, core/audit_logger.py,
routers/scripts.py), a parallel build that landed directly on main while
this branch was in progress.

Run: cd backend && python -m pytest tests/test_v29_batch1_reconciliation.py -q

These tests specifically target the real bugs found and fixed while
merging Batch 1 in -- every one of them was reproduced against a live
FastAPI app + real DuckDB backend before being fixed (see
BACKEND_BATCH1_BUILD_SUMMARY.md's reconciliation note and
docs/v2.9-batch1-reconciliation.md for the full writeup):

  1. backend/app.py had a literal syntax error (PowerShell `` `n `` escape
     sequences instead of real newlines) that made the whole backend fail
     to import.
  2. core/webhook_dispatcher.py imported aiohttp unconditionally without
     declaring it in requirements.txt -- once (1) was fixed, this crashed
     routers/resonance.py's import and disabled the *entire* /resonance
     router, this branch's own /automation-settings endpoints included.
  3. core/audit_logger.py wrote to a `pqc_audit_log` table with a totally
     different, incompatible schema (the real one is used by
     crypto/pqc_manager.py for ML-DSA-65 signed agent actions), wrapped in
     a bare except: pass -- so the "immutable audit trail" persisted zero
     rows.
  4. database.py created five new tables with `DEFAULT nextval('seq_...')`
     primary keys BEFORE creating those sequences -- DuckDB resolves the
     sequence reference at CREATE TABLE time, so this raised
     CatalogException on the very first fresh-database initialize_schema().
  5. core/enforcement.py's self.logger.log(...) calls were all missing the
     required `action` argument; enforce_isolation()'s
     webhook_dispatcher.dispatch(...) call was missing the required
     `webhook_url` argument.
  6. core/enforcement.py's _persist_isolation()/_fetch_isolation() stored
     isolation state as a JSON blob inside agent_logs.details, matched
     back via a `LIKE '%"<id>"%'` substring search ordered by a timestamp
     column that never actually changed across updates (it always wrote
     the object's original created_at) -- producing non-deterministic,
     often-stale reads once an isolation had been persisted more than
     once, which every real lifecycle does (create -> simulate/request ->
     enforce -> release).
  7. _execute_isolation_action()/_execute_release_action() returned 100%
     fabricated results regardless of target.

Tests 1-4 are exercised implicitly by every other test file in this suite
actually being able to import app/database/routers at all; this file
covers 5-7 plus an end-to-end lifecycle check that would have caught all
of them at once.
"""

import sys
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(scope="module")
def app():
    from app import app as _app
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _uniq() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Import-time safety: the whole resonance policy-enforcement stack must be
# reachable, independently of each other (bug #2's fix).
# ---------------------------------------------------------------------------

def test_resonance_stack_imports_independently_and_is_available():
    from routers import resonance as r
    assert r.RESONANCE_OK is True
    assert r.ENFORCEMENT_OK is True, getattr(r, "_ENFORCEMENT_ERR", None)
    assert r.AUDIT_LOGGER_OK is True, getattr(r, "_AUDIT_LOGGER_ERR", None)


def test_webhook_dispatcher_degrades_gracefully_without_aiohttp(monkeypatch):
    """Simulates aiohttp being unavailable: the sync dispatch() path (and
    the module import itself) must still work; only dispatch_async() should
    refuse, with a clear error instead of a crash."""
    import core.webhook_dispatcher as wd
    monkeypatch.setattr(wd, "AIOHTTP_AVAILABLE", False)
    monkeypatch.setattr(wd, "aiohttp", None)
    dispatcher = wd.WebhookDispatcher(db_manager=None)
    with pytest.raises(RuntimeError, match="aiohttp"):
        import asyncio
        asyncio.run(dispatcher.dispatch_async("http://example.invalid", "test_event", {"a": 1}))


# ---------------------------------------------------------------------------
# database.py schema: sequences must exist before the tables that
# DEFAULT nextval() off them (bug #4).
# ---------------------------------------------------------------------------

def test_fresh_schema_initializes_without_catalog_exception(tmp_path):
    from database import DuckDBManager
    db_path = tmp_path / "fresh_schema_test.duckdb"
    db = DuckDBManager(str(db_path))  # raises on failure -- that's the test
    for table in ("resonance_policy", "resonance_actions", "resonance_audit_trail",
                  "resonance_isolations", "script_library", "script_executions",
                  "automation_settings"):
        db.conn.execute(f"SELECT COUNT(*) FROM {table}")  # raises if missing


# ---------------------------------------------------------------------------
# AuditLogger: must actually persist to, and read back from, a real table
# with a schema that matches what it writes (bug #3).
# ---------------------------------------------------------------------------

def test_audit_logger_persists_and_verifies_chain(tmp_path):
    from database import DuckDBManager
    from core.audit_logger import AuditLogger

    db = DuckDBManager(str(tmp_path / "audit_logger_test.duckdb"))
    al = AuditLogger(db)

    eid1 = al.log(event_type="isolation_enforced", action="execute_isolation",
                   actor="tester", resource="host-1", result="success",
                   details={"isolation_id": "iso-1"})
    al.log(event_type="isolation_released", action="release_isolation",
           actor="tester", resource="host-1", result="success",
           details={"isolation_id": "iso-1"})

    events = al.list_events(limit=10)
    assert len(events) == 2

    chain = al.verify_chain()
    assert chain["valid"] is True
    assert chain["events_verified"] == 2

    single = al.get_event(eid1)
    assert single["action"] == "execute_isolation"
    assert single["resource"] == "host-1"

    # confirm it actually landed in resonance_audit_trail, not pqc_audit_log
    row = db.conn.execute(
        "SELECT isolation_id FROM resonance_audit_trail WHERE event_id = ?", (eid1,)
    ).fetchone()
    assert row is not None
    assert row[0] == "iso-1"

    stats = al.audit_stats()
    assert stats["total_events"] == 2


def test_audit_logger_persist_failure_is_logged_not_swallowed(tmp_path, caplog):
    """The original _persist_event() wrapped its INSERT in a bare
    try/except: pass, so a broken write failed completely silently. It
    should now at least be logged."""
    from database import DuckDBManager
    from core.audit_logger import AuditLogger

    db = DuckDBManager(str(tmp_path / "audit_logger_fail_test.duckdb"))
    al = AuditLogger(db)
    db.conn.execute("DROP TABLE resonance_audit_trail")

    import logging
    with caplog.at_level(logging.ERROR, logger="core.audit_logger"):
        al.log(event_type="x", action="y")
    assert any("resonance_audit_trail insert failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# AuditedHostIsolationEngine: full lifecycle, real persistence, non-fabricated
# results (bugs #5, #6, #7).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_isolation_enforce_release_lifecycle_end_to_end(client):
    hostname = f"host-{_uniq()}"
    exec_resp = await client.post("/api/resonance/enforce/execute", json={
        "target_hostname": hostname, "target_ip_address": "10.0.0.9",
        "target_os": "linux", "threat_severity": 0.9,
        "isolation_mode": "network_only", "justification": "reconciliation test",
        "requested_by": "tester", "auto_approve": True,
    })
    assert exec_resp.status_code == 200, exec_resp.text
    body = exec_resp.json()
    assert body["status"] == "enforced"
    isolation_id = body["isolation_id"]
    # The enforcement_result must be honest, not fabricated: no live
    # EDR/firewall agent is configured in this test environment, so it
    # must say so rather than claim invented interface names/rule counts.
    result = body["enforcement_result"]
    assert result["result"] in ("not_configured", "success")
    assert "affected_interfaces" not in result
    assert "firewall_rules_added" not in result

    status_resp = await client.get(f"/api/resonance/enforce/{isolation_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "active"

    release_resp = await client.post("/api/resonance/enforce/release", json={
        "isolation_id": isolation_id, "released_by": "tester",
    })
    assert release_resp.status_code == 200, release_resp.text
    assert release_resp.json()["status"] == "released"

    status_resp2 = await client.get(f"/api/resonance/enforce/{isolation_id}/status")
    assert status_resp2.json()["status"] == "released"

    # exactly one row for this isolation -- no duplicate/stale rows from
    # the old JSON-blob-in-agent_logs persistence path
    from database import get_db_manager
    db = get_db_manager()
    count = db.conn.execute(
        "SELECT COUNT(*) FROM resonance_isolations WHERE isolation_id = ?", (isolation_id,)
    ).fetchone()[0]
    assert count == 1


@pytest.mark.asyncio
async def test_resonance_policies_crud_uses_distinct_table_from_automation_settings(client):
    """resonance_policy (Batch 1, named multi-row policy objects) and
    automation_settings (this branch, single-row global knobs) must not
    collide -- this is what the rename from resonance_policy ->
    automation_settings on this branch's own table was for."""
    create_resp = await client.post("/api/resonance/policies", json={
        "policy_name": f"policy-{_uniq()}", "threat_threshold": 0.75,
    })
    assert create_resp.status_code == 201, create_resp.text

    list_resp = await client.get("/api/resonance/policies")
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] >= 1

    settings_resp = await client.get("/api/resonance/automation-settings")
    assert settings_resp.status_code == 200
    keys = {p["policy_key"] for p in settings_resp.json()["policy"]}
    assert "response_auto_stage_threshold" in keys
