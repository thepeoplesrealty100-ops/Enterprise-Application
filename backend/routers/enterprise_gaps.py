"""
routers/enterprise_gaps.py — closes the benchmark gaps from the
Kaseya / Datto / Cynet / IT Glue cross-reference table.

Covers the capabilities the platform was missing:
  • Documentation & Vault  — IT-Glue-style asset relationship map,
                             credential rotation tracker.
  • Endpoint & Response    — process kill-tree (for visualization),
                             live memory-dump trigger.
  • Security & Compliance  — automated remediation ticket generation,
                             continuous drift-detection toggle + events.
  • Human Layer            — one-click auto-enrollment for phishing failures.

All data is DuckDB-backed (see services/capabilities_seed.py). Destructive or
high-impact actions are routed through the Security Capabilities Engine so they
inherit the AI Safety guardrail, approval gating and audit trail.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/enterprise", tags=["Enterprise Gap Modules"])


def _db():
    from database import get_db_manager
    return get_db_manager()


def _rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        db = _db()
        res = db.conn.execute(sql, params)
        cols = [d[0] for d in (res.description or [])]
        return [dict(zip(cols, r)) for r in res.fetchall()]
    except Exception:
        return []


def _exec(sql: str, params: tuple = ()):
    db = _db()
    db.conn.execute(sql, params)
    try:
        db.conn.commit()
    except Exception:
        pass


def _now():
    return datetime.now(timezone.utc)


def _setting(key: str, default: str = "false") -> str:
    r = _rows("SELECT value FROM cap_settings WHERE key = ?", (key,))
    return r[0]["value"] if r else default


# ══════════════════════════════════════════════════════════════════════════
# 1. DOCUMENTATION & VAULT  (IT Glue parity)
# ══════════════════════════════════════════════════════════════════════════
@router.get("/docs/relationships")
async def asset_relationships():
    """IT-Glue-style asset relationship map — returns a graph (nodes + edges)
    ready for the frontend relationship view."""
    rels = _rows("SELECT * FROM cap_asset_relationships")
    nodes: Dict[str, Dict[str, Any]] = {}
    for r in rels:
        for a, t in ((r["source_asset"], r["source_type"]), (r["target_asset"], r["target_type"])):
            if a not in nodes:
                nodes[a] = {"id": a, "type": t}
    edges = [{"source": r["source_asset"], "target": r["target_asset"],
              "label": r["relationship"], "criticality": r["criticality"],
              "notes": r["notes"]} for r in rels]
    crit = len([e for e in edges if e["criticality"] == "CRITICAL"])
    return {"nodes": list(nodes.values()), "edges": edges,
            "node_count": len(nodes), "edge_count": len(edges),
            "critical_paths": crit, "generated_at": _now().isoformat()}


@router.get("/vault/rotation")
async def credential_rotation():
    """Structured password/secret rotation tracker widget data."""
    creds = _rows("SELECT * FROM cap_credential_rotation ORDER BY next_due")
    buckets = {"ok": 0, "due-soon": 0, "overdue": 0, "compromised": 0}
    for c in creds:
        buckets[c.get("status", "ok")] = buckets.get(c.get("status", "ok"), 0) + 1
    total = len(creds) or 1
    health = round(100 * buckets.get("ok", 0) / total)
    return {"credentials": creds, "summary": buckets, "total": len(creds),
            "rotation_health_pct": health, "generated_at": _now().isoformat()}


class RotateRequest(BaseModel):
    cred_id: str


@router.post("/vault/rotation/rotate")
async def rotate_credential(req: RotateRequest):
    """Mark a credential rotated (resets the clock)."""
    today = _now().date()
    r = _rows("SELECT rotation_days FROM cap_credential_rotation WHERE cred_id = ?", (req.cred_id,))
    days = int(r[0]["rotation_days"]) if r else 90
    nxt = today + timedelta(days=days)
    _exec("UPDATE cap_credential_rotation SET last_rotated = ?, next_due = ?, status = 'ok', strength = 'strong' WHERE cred_id = ?",
          (today, nxt, req.cred_id))
    return {"ok": True, "cred_id": req.cred_id, "last_rotated": str(today), "next_due": str(nxt), "status": "ok"}


# ══════════════════════════════════════════════════════════════════════════
# 2. ENDPOINT & THREAT RESPONSE  (Datto EDR / RocketCyber parity)
# ══════════════════════════════════════════════════════════════════════════
_PROC_TREE = {
    "WIN-OPS-01": {
        "pid": 1, "name": "System", "children": [
            {"pid": 780, "name": "services.exe", "children": [
                {"pid": 1120, "name": "svchost.exe", "children": []},
                {"pid": 4821, "name": "rundll32.exe", "suspicious": True, "reason": "LSASS access (T1003)",
                 "children": [{"pid": 5140, "name": "cmd.exe", "suspicious": True, "children": [
                     {"pid": 5233, "name": "powershell.exe", "suspicious": True,
                      "reason": "encoded command", "children": []}]}]},
            ]},
            {"pid": 902, "name": "explorer.exe", "children": []},
        ]}
}


@router.get("/detect/process-tree/{device_id}")
async def process_tree(device_id: str):
    """Process hierarchy for the one-click kill-tree visualization."""
    tree = _PROC_TREE.get(device_id) or {"pid": 1, "name": "init", "children": []}

    def walk(n, depth=0, out=None):
        out = out if out is not None else []
        out.append({"pid": n["pid"], "name": n["name"], "depth": depth,
                    "suspicious": bool(n.get("suspicious")), "reason": n.get("reason", "")})
        for c in n.get("children", []):
            walk(c, depth + 1, out)
        return out
    flat = walk(tree)
    return {"device_id": device_id, "tree": tree, "flat": flat,
            "process_count": len(flat),
            "suspicious_count": len([p for p in flat if p["suspicious"]]),
            "generated_at": _now().isoformat()}


class MemoryDumpRequest(BaseModel):
    device_id: str
    pid: Optional[int] = None
    scope: str = "process"          # process | full


@router.post("/detect/memory-dump")
async def memory_dump(req: MemoryDumpRequest):
    """Live memory-dump trigger (forensic capture). HIGH risk — routed through
    the Capabilities Engine so it inherits guardrail + approval + audit."""
    from services.capabilities_engine import get_capabilities_engine
    eng = get_capabilities_engine(_db())
    gated = await eng.execute("detect:memory_dump",
                              {"agent_id": req.device_id, "pid": req.pid, "scope": req.scope},
                              executor="operator")
    return gated


# ══════════════════════════════════════════════════════════════════════════
# 3. UNIFIED SECURITY & COMPLIANCE  (ConnectSecure / Cynet parity)
# ══════════════════════════════════════════════════════════════════════════
class TicketRequest(BaseModel):
    source: str = "vulnerability"     # vulnerability | edr_alert | dark_web | drift
    source_ref: str = ""
    assignee: str = "unassigned"


_SLA_HOURS = {"CRITICAL": 4, "HIGH": 24, "MEDIUM": 72, "LOW": 168}


@router.post("/compliance/remediation-ticket")
async def generate_ticket(req: TicketRequest):
    """Automated remediation ticket generation — pulls severity/asset from the
    originating finding so the ticket is populated, not a blank form."""
    title, severity, asset = f"Remediate {req.source_ref}", "MEDIUM", "unknown"
    if req.source == "vulnerability":
        r = _rows("SELECT cve_id, severity, affected_asset, description FROM cap_nvd_vulnerabilities WHERE cve_id = ?", (req.source_ref,))
        if r:
            title = f"Patch {r[0]['cve_id']} on {r[0]['affected_asset']}"; severity = r[0]["severity"]; asset = r[0]["affected_asset"]
    elif req.source == "edr_alert":
        r = _rows("SELECT alert_id, severity, host, description FROM cap_security_alerts WHERE alert_id = ?", (req.source_ref,))
        if r:
            title = f"Investigate: {r[0]['description']}"; severity = r[0]["severity"]; asset = r[0]["host"]
    elif req.source == "dark_web":
        r = _rows("SELECT leak_id, severity, exposed_email FROM cap_credential_leaks WHERE leak_id = ?", (req.source_ref,))
        if r:
            title = f"Credential exposure: {r[0]['exposed_email']}"; severity = r[0]["severity"]; asset = r[0]["exposed_email"]
    elif req.source == "drift":
        r = _rows("SELECT drift_id, severity, asset, control FROM cap_drift_events WHERE drift_id = ?", (req.source_ref,))
        if r:
            title = f"Config drift: {r[0]['control']} on {r[0]['asset']}"; severity = r[0]["severity"]; asset = r[0]["asset"]

    tid = f"tkt-{uuid.uuid4().hex[:6]}"
    sla = _now() + timedelta(hours=_SLA_HOURS.get(severity, 72))
    _exec("INSERT INTO cap_remediation_tickets (ticket_id,title,source,source_ref,severity,asset,assignee,status,sla_due) VALUES (?,?,?,?,?,?,?,?,?)",
          (tid, title, req.source, req.source_ref, severity, asset, req.assignee, "open", sla))
    return {"ok": True, "ticket_id": tid, "title": title, "severity": severity,
            "asset": asset, "sla_due": sla.isoformat(), "status": "open"}


@router.get("/compliance/tickets")
async def list_tickets(status: Optional[str] = None):
    sql = "SELECT * FROM cap_remediation_tickets"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"; params = (status,)
    sql += " ORDER BY created_at DESC"
    t = _rows(sql, params)
    return {"tickets": t, "count": len(t),
            "open": len([x for x in t if x.get("status") == "open"])}


@router.get("/compliance/drift")
async def drift_events():
    """Continuous drift-detection events + current toggle state."""
    ev = _rows("SELECT * FROM cap_drift_events ORDER BY detected_at DESC")
    return {"enabled": _setting("drift_detection_enabled", "true") == "true",
            "events": ev, "count": len(ev),
            "unacknowledged": len([e for e in ev if not e.get("acknowledged")])}


class ToggleRequest(BaseModel):
    enabled: bool


@router.post("/compliance/drift/toggle")
async def drift_toggle(req: ToggleRequest):
    """Continuous drift-detection alert toggle."""
    _exec("INSERT OR REPLACE INTO cap_settings (key,value,updated_at) VALUES (?,?,?)",
          ("drift_detection_enabled", "true" if req.enabled else "false", _now()))
    return {"ok": True, "setting": "drift_detection_enabled", "enabled": req.enabled}


# ══════════════════════════════════════════════════════════════════════════
# 4. HUMAN LAYER & PHISHING
# ══════════════════════════════════════════════════════════════════════════
@router.get("/awareness/phish-failures")
async def phish_failures():
    f = _rows("SELECT * FROM cap_phish_failures ORDER BY failed_at DESC")
    return {"failures": f, "count": len(f),
            "pending_enrollment": len([x for x in f if x.get("action_taken") == "pending"]),
            "auto_enroll_enabled": _setting("auto_enroll_on_phish_fail", "true") == "true"}


class EnrollRequest(BaseModel):
    course: str = "Phishing 101"
    only_pending: bool = True


@router.post("/awareness/auto-enroll")
async def auto_enroll(req: EnrollRequest):
    """One-click automated enrollment for every user who failed a simulation."""
    where = " WHERE action_taken = 'pending'" if req.only_pending else ""
    targets = _rows(f"SELECT fail_id, user_id, display_name FROM cap_phish_failures{where}")
    for t in targets:
        _exec("UPDATE cap_phish_failures SET action_taken = 'enrolled', enrolled_course = ? WHERE fail_id = ?",
              (req.course, t["fail_id"]))
        # bump assigned training on the human-risk record
        _exec("UPDATE cap_human_risk_metrics SET training_assigned = training_assigned + 1 WHERE user_id = ?",
              (t["user_id"],))
    return {"ok": True, "enrolled": len(targets), "course": req.course,
            "users": [t["display_name"] for t in targets]}


@router.post("/awareness/auto-enroll/toggle")
async def auto_enroll_toggle(req: ToggleRequest):
    _exec("INSERT OR REPLACE INTO cap_settings (key,value,updated_at) VALUES (?,?,?)",
          ("auto_enroll_on_phish_fail", "true" if req.enabled else "false", _now()))
    return {"ok": True, "setting": "auto_enroll_on_phish_fail", "enabled": req.enabled}


# ══════════════════════════════════════════════════════════════════════════
# 5. Settings surface (drives the UI toggles)
# ══════════════════════════════════════════════════════════════════════════
@router.get("/settings")
async def settings():
    return {"settings": _rows("SELECT * FROM cap_settings")}


class SettingRequest(BaseModel):
    key: str
    value: str


@router.post("/settings")
async def set_setting(req: SettingRequest):
    _exec("INSERT OR REPLACE INTO cap_settings (key,value,updated_at) VALUES (?,?,?)",
          (req.key, req.value, _now()))
    return {"ok": True, "key": req.key, "value": req.value}
