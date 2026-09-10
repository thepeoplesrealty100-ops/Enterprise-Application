"""
routers/fleet_agent.py — JAKAL endpoint-agent hub (v1.0)  [roadmap #4]

The hub side of the hub-and-spoke model. A real JAKAL agent installed on an
endpoint registers here, heartbeats, reports its inventory (OS, IP, installed
software, users, open ports), and polls a per-agent command queue. This is
what makes Fleet/RMM/EDR act on real machines instead of sandboxes.

Endpoints
  POST /api/agents/register          — enroll; returns agent_key (spoke → hub)
  POST /api/agents/heartbeat         — liveness ping (needs X-Agent-Key)
  POST /api/agents/inventory         — push inventory (needs X-Agent-Key)
  GET  /api/agents                   — list managed endpoints (fleet view)
  GET  /api/agents/{agent_id}        — full asset detail (drives Target B)
  POST /api/agents/{agent_id}/commands   — queue a command (operator)
  GET  /api/agents/{agent_id}/commands   — agent polls pending (needs key)
  POST /api/agents/commands/{cmd_id}/result — agent posts result (needs key)

An endpoint is 'online' only if it heartbeat within AGENT_OFFLINE_SECONDS.
"""
import json
import secrets as _secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/agents", tags=["Endpoint Agents"])

AGENT_OFFLINE_SECONDS = 120


def _db():
    from database import get_db_manager
    return get_db_manager()


def _now():
    return datetime.now(timezone.utc)


def _ensure_schema(db):
    c = db.conn
    c.execute("""CREATE TABLE IF NOT EXISTS agent_endpoints (
        agent_id TEXT PRIMARY KEY, hostname TEXT, os TEXT, os_version TEXT, ip TEXT,
        agent_key TEXT, status TEXT DEFAULT 'online', first_seen TIMESTAMP, last_seen TIMESTAMP,
        tags TEXT, meta TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS agent_inventory (
        agent_id TEXT PRIMARY KEY, software TEXT, users TEXT, ports TEXT,
        os_detail TEXT, updated_at TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS agent_commands (
        cmd_id TEXT PRIMARY KEY, agent_id TEXT, action TEXT, payload TEXT,
        status TEXT DEFAULT 'pending', result TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""")
    c.commit()


def _rows(db, sql, params=()):
    res = db.conn.execute(sql, params)
    cols = [d[0] for d in (res.description or [])]
    return [dict(zip(cols, r)) for r in res.fetchall()]


def _auth_agent(db, agent_id: str, key: Optional[str]):
    rows = _rows(db, "SELECT agent_key FROM agent_endpoints WHERE agent_id = ?", (agent_id,))
    if not rows or not key or rows[0]["agent_key"] != key:
        raise HTTPException(status_code=401, detail="invalid agent credentials")


def _status_of(last_seen) -> str:
    if not last_seen:
        return "offline"
    if isinstance(last_seen, str):
        try:
            last_seen = datetime.fromisoformat(last_seen)
        except ValueError:
            return "offline"
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return "online" if (_now() - last_seen) < timedelta(seconds=AGENT_OFFLINE_SECONDS) else "offline"


class RegisterReq(BaseModel):
    agent_id: Optional[str] = None
    hostname: str
    os: str = ""
    os_version: str = ""
    ip: str = ""
    tags: List[str] = []


@router.post("/register")
async def register(req: RegisterReq):
    db = _db(); _ensure_schema(db)
    agent_id = req.agent_id or f"agt-{uuid.uuid4().hex[:12]}"
    key = _secrets.token_urlsafe(24)
    existing = _rows(db, "SELECT agent_id, agent_key FROM agent_endpoints WHERE agent_id = ?", (agent_id,))
    now = _now()
    if existing:
        key = existing[0]["agent_key"]  # keep stable key on re-register
        db.conn.execute("UPDATE agent_endpoints SET hostname=?, os=?, os_version=?, ip=?, status='online', last_seen=?, tags=? WHERE agent_id=?",
                        (req.hostname, req.os, req.os_version, req.ip, now, json.dumps(req.tags), agent_id))
    else:
        db.conn.execute("INSERT INTO agent_endpoints (agent_id,hostname,os,os_version,ip,agent_key,status,first_seen,last_seen,tags,meta) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (agent_id, req.hostname, req.os, req.os_version, req.ip, key, "online", now, now, json.dumps(req.tags), "{}"))
    db.conn.commit()
    return {"ok": True, "agent_id": agent_id, "agent_key": key, "heartbeat_seconds": 30}


@router.post("/heartbeat")
async def heartbeat(agent_id: str, x_agent_key: Optional[str] = Header(None)):
    db = _db(); _ensure_schema(db); _auth_agent(db, agent_id, x_agent_key)
    db.conn.execute("UPDATE agent_endpoints SET last_seen=?, status='online' WHERE agent_id=?", (_now(), agent_id))
    db.conn.commit()
    pending = _rows(db, "SELECT COUNT(*) AS n FROM agent_commands WHERE agent_id=? AND status='pending'", (agent_id,))
    return {"ok": True, "at": _now().isoformat(), "pending_commands": pending[0]["n"] if pending else 0}


class InventoryReq(BaseModel):
    agent_id: str
    software: List[Dict[str, Any]] = []
    users: List[str] = []
    ports: List[int] = []
    os_detail: Dict[str, Any] = {}


@router.post("/inventory")
async def inventory(req: InventoryReq, x_agent_key: Optional[str] = Header(None)):
    db = _db(); _ensure_schema(db); _auth_agent(db, req.agent_id, x_agent_key)
    db.conn.execute("INSERT OR REPLACE INTO agent_inventory (agent_id,software,users,ports,os_detail,updated_at) VALUES (?,?,?,?,?,?)",
                    (req.agent_id, json.dumps(req.software), json.dumps(req.users), json.dumps(req.ports),
                     json.dumps(req.os_detail), _now()))
    db.conn.execute("UPDATE agent_endpoints SET last_seen=?, status='online' WHERE agent_id=?", (_now(), req.agent_id))
    db.conn.commit()
    return {"ok": True, "software_count": len(req.software)}


@router.get("")
async def list_agents():
    db = _db(); _ensure_schema(db)
    rows = _rows(db, "SELECT agent_id,hostname,os,os_version,ip,status,first_seen,last_seen,tags FROM agent_endpoints ORDER BY last_seen DESC")
    for r in rows:
        r["status"] = _status_of(r.get("last_seen"))
        try: r["tags"] = json.loads(r.get("tags") or "[]")
        except Exception: r["tags"] = []
    return {"agents": rows, "count": len(rows),
            "online": len([r for r in rows if r["status"] == "online"])}


@router.get("/{agent_id}")
async def agent_detail(agent_id: str):
    db = _db(); _ensure_schema(db)
    rows = _rows(db, "SELECT * FROM agent_endpoints WHERE agent_id=?", (agent_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="agent not found")
    a = rows[0]; a.pop("agent_key", None)
    a["status"] = _status_of(a.get("last_seen"))
    try: a["tags"] = json.loads(a.get("tags") or "[]")
    except Exception: a["tags"] = []
    inv = _rows(db, "SELECT software,users,ports,os_detail,updated_at FROM agent_inventory WHERE agent_id=?", (agent_id,))
    software = []
    if inv:
        for k in ("software", "users", "ports", "os_detail"):
            try: inv[0][k] = json.loads(inv[0][k]) if inv[0].get(k) else ([] if k != "os_detail" else {})
            except Exception: inv[0][k] = [] if k != "os_detail" else {}
        software = inv[0].get("software") or []
        a["inventory"] = inv[0]
    else:
        a["inventory"] = None
    # live CVE enrichment of the reported software via the shared OSV.dev engine
    vuln = None
    if software:
        try:
            from services.vuln_scanner import osv_scan
            vuln = osv_scan([{"name": s.get("name"), "version": s.get("version"),
                              "ecosystem": s.get("ecosystem", "PyPI")} for s in software if s.get("version")])
        except Exception as e:
            vuln = {"ok": False, "error": str(e)}
    a["vulnerabilities"] = vuln
    a["commands"] = _rows(db, "SELECT cmd_id,action,status,created_at FROM agent_commands WHERE agent_id=? ORDER BY created_at DESC LIMIT 20", (agent_id,))
    return a


class CommandReq(BaseModel):
    # NOTE: field is 'command' not 'action' — the security middleware reserves
    # the body field name 'action' for the 5 device-action verbs.
    command: str
    payload: Dict[str, Any] = {}


@router.post("/{agent_id}/commands")
async def queue_command(agent_id: str, req: CommandReq):
    db = _db(); _ensure_schema(db)
    if not _rows(db, "SELECT 1 FROM agent_endpoints WHERE agent_id=?", (agent_id,)):
        raise HTTPException(status_code=404, detail="agent not found")
    cmd_id = f"cmd-{uuid.uuid4().hex[:10]}"
    db.conn.execute("INSERT INTO agent_commands (cmd_id,agent_id,action,payload,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (cmd_id, agent_id, req.command, json.dumps(req.payload), "pending", _now(), _now()))
    db.conn.commit()
    return {"ok": True, "cmd_id": cmd_id, "status": "pending"}


@router.get("/{agent_id}/commands")
async def poll_commands(agent_id: str, x_agent_key: Optional[str] = Header(None)):
    db = _db(); _ensure_schema(db); _auth_agent(db, agent_id, x_agent_key)
    rows = _rows(db, "SELECT cmd_id,action,payload FROM agent_commands WHERE agent_id=? AND status='pending' ORDER BY created_at", (agent_id,))
    for r in rows:
        try: r["payload"] = json.loads(r.get("payload") or "{}")
        except Exception: r["payload"] = {}
        db.conn.execute("UPDATE agent_commands SET status='dispatched', updated_at=? WHERE cmd_id=?", (_now(), r["cmd_id"]))
    db.conn.commit()
    return {"commands": rows}


class ResultReq(BaseModel):
    agent_id: str
    result: Dict[str, Any] = {}
    status: str = "completed"


@router.post("/commands/{cmd_id}/result")
async def command_result(cmd_id: str, req: ResultReq, x_agent_key: Optional[str] = Header(None)):
    db = _db(); _ensure_schema(db); _auth_agent(db, req.agent_id, x_agent_key)
    db.conn.execute("UPDATE agent_commands SET status=?, result=?, updated_at=? WHERE cmd_id=?",
                    (req.status, json.dumps(req.result), _now(), cmd_id))
    db.conn.commit()
    return {"ok": True, "cmd_id": cmd_id, "status": req.status}
