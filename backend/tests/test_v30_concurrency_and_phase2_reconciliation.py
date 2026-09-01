"""
backend/tests/test_v30_concurrency_and_phase2_reconciliation.py
JAKAL v2.10 — reconciliation of a third independent wave ("Phase 2-5 UI
Bridge + Security Hardening") that landed on main while the v2.9 Batch 1
reconciliation above was itself being pushed. Covers the real bugs found
and fixed while merging it in, all reproduced before being fixed:

  1. backend/config.py and the new backend/config/openapi_config.py
     collided (a module and a same-named package can't coexist) --
     `ModuleNotFoundError: No module named 'config.openapi_config'; 'config'
     is not a package`. Same for backend/middleware.py vs.
     backend/middleware/security_hardening.py. Fixed by converting both
     into real packages (config.py -> config/__init__.py, middleware.py ->
     middleware/__init__.py).
  2. routers/ui_bridge.py defined GET /api/fabric/status,
     GET /api/scripts/catalog, GET/POST /api/resonance/policies, and
     GET /api/resonance/audit -- exact path collisions with
     routers/fabric.py, routers/scripts.py, and routers/resonance.py
     (registered earlier in app.py, so they always won). Two different
     frontends (integration.js and the new frontend/js/api-client.js) call
     some of the same paths expecting different response shapes from
     different backends, so this wasn't just dead code -- reordering
     registration to "fix" it would have silently broken whichever
     frontend lost. Renamed the four colliding routes under /dashboard/.
  3. GET /api/dashboard/matrix selected findings.cvss_score, a column that
     doesn't exist in the real findings schema -- a live BinderException
     on every call.
  4. middleware/security_hardening.py's InputValidator blocklisted
     individual characters and bare dictionary words (SELECT, INSERT,
     EXEC, ';', "'", '(', '{', '~', ...) rather than actual attack shapes,
     applied to every query param, path param, and JSON body field across
     the whole app -- a perfectly ordinary string like "payload-exec-123"
     (contains "exec" as a \\b-delimited word) was rejected as
     "sql_injection" with a 400. Retuned to match real attack shapes.
  5. Its "action" field whitelist allowed "block"/"monitor" (not real
     values) while rejecting "reset_pass"/"release" (which
     DeviceActionRequest.action documents as valid) -- 2 of 5 real device
     actions were unreachable via POST /api/dashboard/fleet/{id}/action.
  6. CRITICAL: database.py's DuckDBManager wrapped a bare
     duckdb.Connection shared across the whole process. A bare-minimum
     repro (10 threads each looping conn.execute() against one shared
     connection) reliably segfaults the Python process (SIGSEGV, exit
     139) -- and FastAPI's run_in_threadpool(), used by every router,
     genuinely runs different requests' DB calls on different worker
     threads whenever two requests overlap, which is ordinary under real
     concurrent usage (two browser tabs, one tab plus an open SSE stream),
     not a synthetic edge case. Reproduced against a live uvicorn instance
     via the phase3 integration suite's concurrent-SSE-listeners test,
     which crashed the whole server. Fixed with a `_LockedConnection`
     wrapper (see database.py) that serializes access and eagerly
     materializes results, verified against the same threaded repro with
     zero errors across thousands of concurrent queries.

Run: cd backend && python -m pytest tests/test_v30_concurrency_and_phase2_reconciliation.py -q
"""

import sys
import threading
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


# ---------------------------------------------------------------------------
# config/ and middleware/ package conversion
# ---------------------------------------------------------------------------

def test_config_and_middleware_are_importable_packages():
    import config
    import config.openapi_config
    import middleware
    import middleware.security_hardening
    assert hasattr(config, "get_config")
    assert hasattr(middleware, "TimingAndSecurityMiddleware")


# ---------------------------------------------------------------------------
# ui_bridge.py route collisions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_native_and_dashboard_endpoints_coexist_with_distinct_shapes(client):
    native = await client.get("/api/fabric/status")
    dashboard = await client.get("/api/dashboard/fabric/status")
    assert native.status_code == 200
    assert dashboard.status_code == 200
    # Different backends, different shapes -- fabric.py's native shape has
    # no "overall_score"/"by_pillar", ui_bridge.py's dashboard shape does.
    assert "overall_score" not in native.json()
    assert "overall_score" in dashboard.json()

    native_scripts = await client.get("/api/scripts/catalog")
    dashboard_scripts = await client.get("/api/dashboard/scripts/catalog")
    assert native_scripts.status_code == 200
    assert dashboard_scripts.status_code == 200
    assert "scripts" in native_scripts.json()
    assert "pagination" in dashboard_scripts.json()

    native_policies = await client.get("/api/resonance/policies")
    dashboard_policies = await client.get("/api/dashboard/resonance/policies")
    assert native_policies.status_code == 200
    assert dashboard_policies.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_matrix_does_not_reference_nonexistent_column(client):
    response = await client.get("/api/dashboard/matrix")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "matrix" in body
    assert set(body["matrix"].keys()) == {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


# ---------------------------------------------------------------------------
# InputValidator false positives
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_input_validator_does_not_false_positive_on_ordinary_strings(client):
    from middleware.security_hardening import InputValidator

    # These all previously matched the old bare-keyword/character
    # blocklist and were rejected.
    for benign in [
        "payload-exec-123", "don't", "T1059(001)", "select-a-target",
        "create_isolation_request", "update-2026-09-01", "host{prod}",
    ]:
        InputValidator.sanitize_string(benign)  # must not raise

    # Real attack shapes must still be caught.
    for malicious in [
        "1 UNION SELECT username, password FROM users",
        "'; DROP TABLE users; --",
        "admin' OR '1'='1",
    ]:
        with pytest.raises(ValueError):
            InputValidator.sanitize_string(malicious)


def test_action_whitelist_matches_real_device_action_values():
    from middleware.security_hardening import InputValidator
    for action in ["scan", "isolate", "quarantine", "reset_pass", "release"]:
        InputValidator.sanitize_string(action, "action")  # must not raise
    with pytest.raises(ValueError):
        InputValidator.sanitize_string("block", "action")  # never a real value


# ---------------------------------------------------------------------------
# CRITICAL: DuckDB concurrent-access crash fix
# ---------------------------------------------------------------------------

def test_concurrent_db_access_does_not_crash(tmp_path):
    """
    Direct regression test for the SIGSEGV: many threads hammering
    db.conn.execute() concurrently must complete without error and without
    crashing the interpreter (a real crash would kill the whole pytest
    process, not raise a catchable exception -- so this test's mere
    survival, plus correct row counts, is the actual assertion).
    """
    from database import DuckDBManager

    db = DuckDBManager(str(tmp_path / "concurrency_test.duckdb"))
    errors = []

    def worker(n):
        for _ in range(100):
            try:
                rows = db.conn.execute("SELECT * FROM agent_logs LIMIT 5").fetchall()
                cols = [d[0] for d in db.conn.description]
                assert cols == ["id", "timestamp", "event", "action", "status", "operator_id", "details"]
                db.insert_log({
                    "event": f"concurrency-test-{n}", "action": "check",
                    "status": "success", "operator_id": "tester", "details": {},
                })
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    total = db.conn.execute(
        "SELECT COUNT(*) FROM agent_logs WHERE action = 'check'"
    ).fetchall()[0][0]
    assert total == 1500


@pytest.mark.asyncio
async def test_frontend_serves_ui_without_exposing_repo_source(client):
    """
    RECONCILIATION FIX: FRONTEND_DIR's default incorrectly pointed at
    <repo_root>/frontend, one level too deep -- index.html and
    integration.js actually live at the repo root, so GET / never found
    index.html (silently falling back to the bare JSON hint) and
    GET /integration.js 404'd. Fixed by pointing FRONTEND_DIR at the repo
    root. That introduced a second issue: mounting the ENTIRE repo root as
    StaticFiles serves the whole backend source tree and .git over HTTP
    (confirmed live: GET /backend/database.py and GET /.git/config both
    returned 200 with real file contents) -- fixed by serving only the
    specific local assets index.html actually needs through named,
    explicit FileResponse routes instead of mounting the whole tree.

    (js/api-client.js was one such asset when this test was written; it
    and js/integration-loader.js were later found to be dead code -- never
    instantiated anywhere despite being loaded -- and were deleted along
    with the /js mount. See index.html and app.py's frontend-mount comment.)
    """
    root = await client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")

    integration_js = await client.get("/integration.js")
    assert integration_js.status_code == 200

    world_land_map = await client.get("/world_land_map.json")
    assert world_land_map.status_code == 200

    # Must NOT be servable -- these are backend source, git internals, and
    # docs, none of which index.html references.
    for sensitive_path in ["/backend/database.py", "/backend/config/__init__.py",
                            "/.git/config", "/docs/v2.6-global-settings-security-api.md"]:
        resp = await client.get(sensitive_path)
        assert resp.status_code == 404, f"{sensitive_path} should not be servable, got {resp.status_code}"


def test_locked_connection_description_is_correct_after_chained_and_separate_access(tmp_path):
    """Covers both usage patterns in this codebase: chained
    (execute(...).fetchall()) and separate-statement (execute(...); later
    read .description) -- both must reflect the SAME query's columns."""
    from database import DuckDBManager

    db = DuckDBManager(str(tmp_path / "description_test.duckdb"))

    result = db.conn.execute("SELECT id, event FROM agent_logs LIMIT 0")
    assert [d[0] for d in result.description] == ["id", "event"]

    db.conn.execute("SELECT id, event, action FROM agent_logs LIMIT 0")
    assert [d[0] for d in db.conn.description] == ["id", "event", "action"]
