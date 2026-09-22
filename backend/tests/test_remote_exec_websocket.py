"""
backend/tests/test_remote_exec_websocket.py
routers/remote_exec.py's Live Remote Execution Engine -- WebSocket layer.

Run: cd backend && python -m pytest tests/test_remote_exec_websocket.py -q

Regression context: `websockets` (or `wsproto`) was never listed in
backend/requirements.txt, despite remote_exec.py's WebSocket route
(/ws/exec/{execution_id}) being the only way its live-streamed output
was ever meant to reach a viewer. uvicorn has no ASGI WebSocket
implementation of its own -- without one of these installed, it silently
falls back to HTTP-only and treats every WebSocket handshake as a plain
HTTP request that matches no route, returning a completely generic
{"detail": "Not Found"} 404 with the usual security headers attached.
Confirmed live: this backend had never once been able to open a
WebSocket connection in any environment where only requirements.txt
governed the install -- indistinguishable from a genuinely missing or
mistyped route unless you specifically know to check for the ASGI
server's own websocket support, which nothing in this codebase did.

This suite uses Starlette's TestClient (the only httpx-based client in
this test suite, ASGITransport, does not support WebSocket connections
at all) specifically so `test_websocket_connects_replays_and_receives_
live_broadcast` fails loudly -- not just skips -- if this dependency
silently disappears from requirements.txt again.
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
sys.modules.setdefault("anthropic", types.ModuleType("anthropic"))


def test_websockets_package_is_installed():
    """
    The exact regression: requirements.txt omitted the one package that
    lets uvicorn speak the WebSocket protocol at all. This assertion is
    intentionally the whole test -- if it's the only one that fails here
    after a dependency change, that is the fix: reinstall the package,
    don't touch application code.
    """
    try:
        websockets = importlib.import_module("websockets")
    except ImportError:
        pytest.fail(
            "The 'websockets' package is not installed. uvicorn has no ASGI "
            "WebSocket implementation of its own -- without this (or "
            "wsproto), every /ws/* route silently 404s as if it doesn't "
            "exist, and routers/remote_exec.py's live execution streaming "
            "has never worked. Add 'websockets>=12.0' back to "
            "backend/requirements.txt."
        )
    assert websockets.__version__


def test_websocket_connects_replays_and_receives_live_broadcast():
    """
    One real WebSocket connection, exercising the whole documented
    protocol in the same order an actual viewer would:
      1. connect -- server replays stored chunks (none exist yet for a
         fresh execution_id) then sends REPLAY_DONE
      2. a second "agent" POSTs a chunk via /api/exec/chunk (the same
         call agent/jakal_agent.py makes after running a real script)
      3. that chunk arrives over the still-open connection as an
         AGENT_STREAM_DATA broadcast -- proving the hub's fan-out
         (ExecHub.broadcast in remote_exec.py) actually reaches a live
         subscriber, not just that a connection can be opened.

    Deliberately ONE connection for both checks, not two sequential
    ones (each its own `with ... as ws:` block): reproduced directly
    that two separate websocket_connect() lifecycles back-to-back hang
    the second one forever (no exception, no timeout -- it just never
    receives). Root cause not fully isolated (Starlette's TestClient
    runs the ASGI app via an anyio portal in a background thread; a
    prior connection's server-side task apparently isn't fully torn
    down before the next one starts). This test avoids that pattern --
    which also happens to match how a real client actually behaves: one
    open connection for the run's whole lifetime, not a fresh one per
    message.

    Also deliberately `client = TestClient(app)`, NOT
    `with TestClient(app) as client:`. The context-manager form runs a
    full ASGI lifespan cycle, and app.py's shutdown hook calls
    db.close() on the single shared DuckDBManager instance
    get_db_manager() always returns (database.py) -- every OTHER test
    module in this suite imports that same singleton, so this file
    closing it would silently break every test that runs after it in
    the same `pytest tests/` process (confirmed: 45 unrelated failures
    the one time this used the `with` form). Skipping the context
    manager skips both startup and shutdown; a bare TestClient still
    handles requests/websockets fine without it, and the shared
    connection survives for every test that runs after this one.
    """
    from starlette.testclient import TestClient
    from app import app

    execution_id = "test-exec-live-broadcast"
    client = TestClient(app)
    with client.websocket_connect(f"/ws/exec/{execution_id}") as ws:
        replay = ws.receive_json()
        assert replay["type"] == "REPLAY_DONE"
        assert replay["executionId"] == execution_id

        resp = client.post("/api/exec/chunk", json={
            "executionId": execution_id, "endpointId": "test-agent",
            "osType": "linux", "streamType": "stdout",
            "outputChunk": "hello from a real chunk\n", "done": True,
        })
        assert resp.status_code == 200

        msg = ws.receive_json()
        assert msg["type"] == "AGENT_STREAM_DATA"
        assert msg["executionId"] == execution_id
        assert msg["endpointId"] == "test-agent"
        assert msg["data"] == "hello from a real chunk\n"
        assert msg["done"] is True
