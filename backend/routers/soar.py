"""
routers/soar.py — real SOAR auto-triage chain (v1.0) [roadmap #7]

Composes the now-real capability actions into an end-to-end incident chain:
  enrich (live threat-intel) → decide → contain (real isolate, approval-gated)
  → ticket (real DB record). Each step executes a genuine action and is
  returned with its real result; nothing is simulated.

  POST /api/soar/auto-triage  {indicator, agent_id?, auto_contain?}
  GET  /api/soar/tickets
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/soar", tags=["SOAR"])


def _db():
    from database import get_db_manager
    return get_db_manager()


def _now():
    return datetime.now(timezone.utc)


def _ensure(db):
    db.conn.execute("""CREATE TABLE IF NOT EXISTS soar_tickets (
        ticket_id TEXT PRIMARY KEY, indicator TEXT, verdict TEXT, agent_id TEXT,
        summary TEXT, steps TEXT, status TEXT, created_at TIMESTAMP)""")
    db.conn.commit()


class TriageReq(BaseModel):
    indicator: str
    agent_id: Optional[str] = None
    auto_contain: bool = False


@router.post("/auto-triage")
async def auto_triage(req: TriageReq):
    from services.capabilities_engine import get_capabilities_engine
    db = _db(); _ensure(db)
    eng = get_capabilities_engine(db)
    steps: List[Dict[str, Any]] = []

    # 1. ENRICH — live threat intel
    intel = await eng.execute("intel:lookup", {"indicator": req.indicator})
    verdict = intel.get("verdict", "unknown")
    steps.append({"step": "enrich", "action": "intel:lookup",
                  "result": {"verdict": verdict, "score": intel.get("score"),
                             "malicious_sources": intel.get("malicious_sources")}})

    malicious = verdict == "malicious"
    # 2. CONTAIN — only when malicious; real isolate action (approval-gated)
    if malicious and req.agent_id:
        contain = await eng.execute("fleet:isolate_host",
                                    {"agent_id": req.agent_id, "reason": f"SOAR: {req.indicator} is {verdict}"},
                                    approved=bool(req.auto_contain))
        steps.append({"step": "contain", "action": "fleet:isolate_host",
                      "result": {"status": contain.get("status"),
                                 "requires_approval": contain.get("requires_approval"),
                                 "approval_id": contain.get("approval_id")}})
    else:
        steps.append({"step": "contain", "action": "fleet:isolate_host",
                      "result": {"status": "skipped", "reason":
                                 "indicator not malicious" if not malicious else "no agent_id supplied"}})

    # 3. TICKET — always record a real remediation ticket
    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    summary = f"{req.indicator} verdict={verdict}" + (f" · endpoint {req.agent_id}" if req.agent_id else "")
    status = "open" if malicious else "informational"
    db.conn.execute("INSERT INTO soar_tickets (ticket_id,indicator,verdict,agent_id,summary,steps,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (ticket_id, req.indicator, verdict, req.agent_id, summary, json.dumps(steps), status, _now()))
    db.conn.commit()
    steps.append({"step": "notify", "action": "compliance:generate_ticket",
                  "result": {"ticket_id": ticket_id, "status": status}})

    return {"ok": True, "indicator": req.indicator, "verdict": verdict, "malicious": malicious,
            "ticket_id": ticket_id, "chain": steps, "at": _now().isoformat()}


@router.get("/tickets")
async def tickets(limit: int = 50):
    db = _db(); _ensure(db)
    res = db.conn.execute("SELECT ticket_id,indicator,verdict,agent_id,summary,status,created_at FROM soar_tickets ORDER BY created_at DESC LIMIT ?", (limit,))
    cols = [d[0] for d in (res.description or [])]
    return {"tickets": [dict(zip(cols, r)) for r in res.fetchall()]}
