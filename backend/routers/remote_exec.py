"""
routers/remote_exec.py — JAKAL RMM Live Remote Execution Engine

Dual-state log architecture:
  * LIVE   — clients subscribe over WebSocket (/ws/exec/{execution_id}) and
             receive AGENT_STREAM_DATA broadcasts as agents stream stdout/stderr.
  * HISTORY— every chunk is persisted to execution_logs, so GET /api/exec/{id}
             replays a past run into the same terminal layout (Historical Audit
             Log View).

Agents (agent/jakal_agent.py) run a queued fleet:execute_script command and POST
their output chunks to /api/exec/chunk in the documented multi-OS payload shape
(windows powershell streams; posix stdout/stderr). The server stores + fans out.
Replaces the old fake capabilities '/ws/remote/{sid}' placeholder.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter(prefix="/api/exec", tags=["Remote Execution"])
ws_router = APIRouter()  # websocket routes mounted without /api prefix


def _db():
    from database import get_db_manager
    return get_db_manager()


def _now():
    return datetime.now(timezone.utc)


def _ensure(db):
    c = db.conn
    c.execute("""CREATE TABLE IF NOT EXISTS executions (
        execution_id TEXT PRIMARY KEY, script_name TEXT, shell TEXT, script_body TEXT,
        targets TEXT, status TEXT DEFAULT 'running', created_at TIMESTAMP, finished_at TIMESTAMP,
        operator TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS execution_logs (
        id BIGINT, execution_id TEXT, endpoint_id TEXT, os_type TEXT, stream_type TEXT,
        chunk TEXT, ts TIMESTAMP)""")
    c.commit()


def _rows(db, sql, p=()):
    r = db.conn.execute(sql, p); cols = [d[0] for d in (r.description or [])]
    return [dict(zip(cols, x)) for x in r.fetchall()]


# ── live subscription registry: execution_id -> set[WebSocket] ────────────
class ExecHub:
    def __init__(self):
        self.subs: Dict[str, set] = {}

    async def subscribe(self, execution_id: str, ws: WebSocket):
        await ws.accept()
        self.subs.setdefault(execution_id, set()).add(ws)

    def unsubscribe(self, execution_id: str, ws: WebSocket):
        s = self.subs.get(execution_id)
        if s and ws in s:
            s.discard(ws)

    async def broadcast(self, execution_id: str, message: dict):
        dead = []
        for ws in list(self.subs.get(execution_id, set())):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unsubscribe(execution_id, ws)


hub = ExecHub()


class RunReq(BaseModel):
    script_name: str = "adhoc"
    shell: str = "bash"                 # bash | powershell | python
    script_body: str = ""
    script_id: Optional[str] = None
    target_endpoint_ids: List[str] = []
    operator: str = "operator"


@router.post("/run")
async def run(req: RunReq):
    """Create an execution and queue a real execute_script command to each
    target endpoint agent (which streams output back to /api/exec/chunk)."""
    db = _db(); _ensure(db)
    # resolve a library script if referenced
    body, name, shell = req.script_body, req.script_name, req.shell
    if req.script_id:
        try:
            from routers.automation import get_script_body
            s = get_script_body(db, req.script_id)
            if s:
                body, name, shell = s["body"], s["name"], s["shell"]
        except Exception:
            pass
    execution_id = f"exec_{uuid.uuid4().hex[:8]}"
    db.conn.execute("INSERT INTO executions (execution_id,script_name,shell,script_body,targets,status,created_at,operator) VALUES (?,?,?,?,?,?,?,?)",
                    (execution_id, name, shell, body, json.dumps(req.target_endpoint_ids), "running", _now(), req.operator))
    db.conn.commit()
    # queue the real command to each agent
    queued = []
    for aid in req.target_endpoint_ids:
        cmd_id = f"cmd-{uuid.uuid4().hex[:10]}"
        db.conn.execute("INSERT INTO agent_commands (cmd_id,agent_id,action,payload,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                        (cmd_id, aid, "fleet:execute_script",
                         json.dumps({"shell": shell, "script": body, "execution_id": execution_id, "chunk_url": "/api/exec/chunk"}),
                         "pending", _now(), _now()))
        queued.append({"endpoint_id": aid, "cmd_id": cmd_id})
    db.conn.commit()
    return {"ok": True, "execution_id": execution_id, "script_name": name, "shell": shell,
            "targets": req.target_endpoint_ids, "queued": queued, "ws": f"/ws/exec/{execution_id}"}


class ChunkReq(BaseModel):
    executionId: str
    endpointId: str
    osType: str = "linux"
    streamType: str = "stdout"          # stdout | stderr | powershell_error
    outputChunk: str = ""
    done: bool = False


@router.post("/chunk")
async def chunk(req: ChunkReq):
    """Agent-to-server stream ingress. Persists the chunk and fans it out to
    every subscribed client in the AGENT_STREAM_DATA broadcast shape."""
    db = _db(); _ensure(db)
    if req.outputChunk:
        import time as _t
        db.conn.execute("INSERT INTO execution_logs (id,execution_id,endpoint_id,os_type,stream_type,chunk,ts) VALUES (?,?,?,?,?,?,?)",
                        (int(_t.time()*1000000) % 9223372036854775807, req.executionId, req.endpointId,
                         req.osType, req.streamType, req.outputChunk, _now()))
    if req.done:
        db.conn.execute("UPDATE executions SET status='completed', finished_at=? WHERE execution_id=? AND status='running'",
                        (_now(), req.executionId))
    db.conn.commit()
    await hub.broadcast(req.executionId, {
        "type": "AGENT_STREAM_DATA", "executionId": req.executionId, "endpointId": req.endpointId,
        "osType": req.osType, "streamType": req.streamType, "data": req.outputChunk,
        "done": req.done, "ts": _now().isoformat(),
    })
    return {"ok": True}


@router.get("")
async def list_exec(limit: int = 50):
    db = _db(); _ensure(db)
    rows = _rows(db, "SELECT execution_id,script_name,shell,targets,status,created_at,finished_at,operator FROM executions ORDER BY created_at DESC LIMIT ?", (limit,))
    for r in rows:
        try: r["targets"] = json.loads(r.get("targets") or "[]")
        except Exception: r["targets"] = []
    return {"executions": rows}


@router.get("/{execution_id}")
async def get_exec(execution_id: str):
    """Historical Audit Log View source: execution meta + all stored chunks,
    grouped by endpoint for the multiplexed terminal."""
    db = _db(); _ensure(db)
    meta = _rows(db, "SELECT * FROM executions WHERE execution_id=?", (execution_id,))
    if not meta:
        return {"ok": False, "error": "execution not found"}
    m = meta[0]
    try: m["targets"] = json.loads(m.get("targets") or "[]")
    except Exception: m["targets"] = []
    logs = _rows(db, "SELECT endpoint_id,os_type,stream_type,chunk,ts FROM execution_logs WHERE execution_id=? ORDER BY ts", (execution_id,))
    by_ep: Dict[str, List[Dict[str, Any]]] = {}
    for l in logs:
        by_ep.setdefault(l["endpoint_id"], []).append(l)
    return {"ok": True, "execution": m, "logs": logs, "by_endpoint": by_ep,
            "endpoints": list(by_ep.keys())}


@ws_router.websocket("/ws/exec/{execution_id}")
async def ws_exec(websocket: WebSocket, execution_id: str):
    """Client (terminal UI) live subscription. On connect, replays stored
    chunks so a late viewer catches up, then streams new ones."""
    await hub.subscribe(execution_id, websocket)
    try:
        db = _db(); _ensure(db)
        for l in _rows(db, "SELECT endpoint_id,os_type,stream_type,chunk,ts FROM execution_logs WHERE execution_id=? ORDER BY ts", (execution_id,)):
            await websocket.send_json({"type": "AGENT_STREAM_DATA", "executionId": execution_id,
                                       "endpointId": l["endpoint_id"], "osType": l["os_type"],
                                       "streamType": l["stream_type"], "data": l["chunk"], "replay": True})
        await websocket.send_json({"type": "REPLAY_DONE", "executionId": execution_id})
        while True:
            await websocket.receive_text()   # keepalive; client may send pings
    except WebSocketDisconnect:
        hub.unsubscribe(execution_id, websocket)
    except Exception:
        hub.unsubscribe(execution_id, websocket)
