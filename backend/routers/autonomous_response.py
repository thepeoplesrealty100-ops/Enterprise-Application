"""
backend/routers/autonomous_response.py — JAKAL Autonomous Response Policy
Engine (v4.0, rebuilt).

Real policy-driven auto-remediation: operators define policies mapping a
real finding's severity/attack_technique to a real Security Capabilities
Engine action (services/capabilities_engine.py — the same 34-action
registry backing routers/capabilities.py and routers/soar.py). Evaluating
a finding against the policy set executes the matched action for real via
SecurityCapabilitiesEngine.execute() — which means every HIGH/CRITICAL
action (isolate_host, quarantine_file, force_password_reset, ...) still
floats a real approval gate (GET /api/capabilities/pending, POST
/api/capabilities/approve/{id}) unless a policy operator explicitly marks
it auto-approved; this router only decides *which* action a finding maps
to, never bypasses the engine's own guardrail or risk gating.

This replaces the original v4.0 router, which exposed an entirely
fictional "nanoswarm" deployment/wave-propagation API (deploy-swarm,
wave-propagate, predict-threat) operating on fabricated units/coordinates
with no persistence and no real threat data. Nothing here reuses that
shape — same rebuild pattern as digital_twin.py / compliance_intelligence.py.
Not used by any frontend page (confirmed: no "autonomous-response"
reference in index.html or js/); frontend wiring is a follow-up.

Endpoints:
  GET    /policies                — list configured policies
  POST   /policies                — create a policy   (response:manage)
  PUT    /policies/{policy_id}    — update a policy    (response:manage)
  DELETE /policies/{policy_id}    — delete a policy    (response:manage)
  POST   /evaluate                — evaluate a real finding, execute the
                                     matched policy's action via the
                                     capabilities engine
  GET    /events                  — history of past evaluations/decisions

Deliberately does not re-expose the capabilities engine's own catalog/
execute/approve/deny surface — that already exists at /api/capabilities/*
(routers/capabilities.py). This router is the policy layer on top of it.
"""
from __future__ import annotations

import json
import logging
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import DuckDBManager, get_db_manager
from dependencies import get_authenticated_user, require_permission
from services.capabilities_engine import get_capabilities_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/autonomous-response", tags=["Autonomous Response"])

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _db() -> DuckDBManager:
    return get_db_manager()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rank(severity: Optional[str]) -> int:
    return _SEVERITY_RANK.get((severity or "").strip().lower(), 0)


def _escape_json_value(v: Any) -> str:
    """JSON-escape a substitution value's *content* (quotes, backslashes,
    control chars) without the surrounding quotes json.dumps() adds --
    the template already supplies those, e.g. "path": "$description"."""
    if v is None:
        return ""
    return json.dumps(str(v))[1:-1]


def _render_template(template: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Fill $field placeholders (string.Template, not str.format -- the
    template IS a JSON object, whose own { } would otherwise collide with
    format-string syntax) in a policy's JSON payload template from real
    finding/request context. Unknown placeholders are left as literal text
    (safe_substitute) rather than raising, since a hand-authored template
    may reference a field this evaluation didn't supply."""
    try:
        safe_context = {k: _escape_json_value(v) for k, v in context.items()}
        filled = string.Template(template).safe_substitute(safe_context)
        payload = json.loads(filled)
        return payload if isinstance(payload, dict) else {}
    except Exception as e:
        logger.warning("Policy payload template render failed: %s", e)
        return {}


def _ensure_schema(db: DuckDBManager) -> None:
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS autonomous_response_policies (
            policy_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            enabled BOOLEAN DEFAULT true,
            min_severity TEXT NOT NULL,
            attack_technique_keyword TEXT,
            action_id TEXT NOT NULL,
            action_payload_template TEXT NOT NULL DEFAULT '{}',
            auto_approve BOOLEAN DEFAULT false,
            created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS autonomous_response_events (
            event_id TEXT PRIMARY KEY,
            finding_id INTEGER,
            target TEXT,
            policy_id TEXT,
            action_id TEXT,
            decision TEXT NOT NULL,
            engine_result TEXT,
            operator_id TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db.conn.commit()
    _seed_default_policies(db)


def _seed_default_policies(db: DuckDBManager) -> None:
    """Seed a small, real, risk-spread starter policy set on first run —
    same explainable-over-opaque philosophy as response.py's
    DEFAULT_PLAYBOOKS. All four action_ids are real entries in
    SecurityCapabilitiesEngine's registry; CRITICAL/HIGH ones stay
    auto_approve=false so the engine's own approval gate still applies."""
    existing = db.conn.execute("SELECT COUNT(*) FROM autonomous_response_policies").fetchone()
    if existing and existing[0] > 0:
        return
    defaults = [
        ("default-critical-isolate", "Auto-isolate host on critical finding", "critical", None,
         "fleet:isolate_host", '{"agent_id": "$target", "reason": "Autonomous response: critical finding — $title"}', False),
        ("default-high-malware-quarantine", "Quarantine file on high-severity malware finding", "high", "malware",
         "detect:quarantine_file", '{"agent_id": "$target", "path": "$description"}', False),
        ("default-medium-yara-scan", "YARA scan on medium-severity finding", "medium", None,
         "detect:scan_yara", '{"agent_id": "$target", "target": "$title", "rule_set": "default"}', True),
        ("default-low-cve-scan", "CVE scan on low-severity finding", "low", None,
         "patch:scan_cve", '{"agent_id": "$target"}', True),
    ]
    for policy_id, name, min_severity, keyword, action_id, template, auto_approve in defaults:
        db.conn.execute(
            """INSERT INTO autonomous_response_policies
               (policy_id, name, enabled, min_severity, attack_technique_keyword,
                action_id, action_payload_template, auto_approve, created_by)
               VALUES (?, ?, true, ?, ?, ?, ?, ?, 'system')""",
            (policy_id, name, min_severity, keyword, action_id, template, auto_approve),
        )
    db.conn.commit()


def _audit(db: DuckDBManager, request: Request, user: dict, action: str, outcome: str,
           resource_id: str = "", detail: Optional[Dict[str, Any]] = None) -> None:
    try:
        db.insert_audit_entry({
            "actor_user_id": user["user_id"], "actor_label": user["username"],
            "action": action, "resource_type": "autonomous_response", "resource_id": resource_id,
            "outcome": outcome, "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("audit write failed for %s", action)


# ══════════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════════

class PolicyCreate(BaseModel):
    name: str = Field(..., max_length=200)
    min_severity: str = Field(..., pattern="^(low|medium|high|critical)$")
    action_id: str = Field(..., max_length=100)
    attack_technique_keyword: Optional[str] = Field(default=None, max_length=200)
    action_payload_template: Dict[str, Any] = Field(default_factory=dict)
    auto_approve: bool = Field(default=False)
    enabled: bool = Field(default=True)


class PolicyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    min_severity: Optional[str] = Field(default=None, pattern="^(low|medium|high|critical)$")
    action_id: Optional[str] = Field(default=None, max_length=100)
    attack_technique_keyword: Optional[str] = Field(default=None, max_length=200)
    action_payload_template: Optional[Dict[str, Any]] = None
    auto_approve: Optional[bool] = None
    enabled: Optional[bool] = None


class EvaluateRequest(BaseModel):
    finding_id: Optional[int] = Field(default=None, description="A real findings.id to evaluate")
    target: str = Field(..., max_length=256, description="Real agent_id/host this finding pertains to")
    # Only used when finding_id is not supplied — evaluate an ad-hoc finding
    # (e.g. from a source that hasn't been persisted to `findings` yet).
    severity: Optional[str] = Field(default=None, pattern="^(low|medium|high|critical)$")
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=2000)
    attack_technique: str = Field(default="", max_length=200)
    operator_id: str = Field(default="system")


def _policy_row_to_dict(r: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(r)
    try:
        r["action_payload_template"] = json.loads(r.get("action_payload_template") or "{}")
    except Exception:
        r["action_payload_template"] = {}
    return r


# ══════════════════════════════════════════════════════════════════════════
# Policies
# ══════════════════════════════════════════════════════════════════════════

@router.get("/policies")
async def list_policies(db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    rows = db.conn.execute(
        "SELECT * FROM autonomous_response_policies ORDER BY created_at ASC"
    ).fetchall()
    cols = [d[0] for d in db.conn.description]
    return {"policies": [_policy_row_to_dict(dict(zip(cols, r))) for r in rows]}


@router.post("/policies", dependencies=[require_permission("response:manage")])
async def create_policy(req: PolicyCreate, request: Request, db: DuckDBManager = Depends(_db),
                         user: dict = Depends(get_authenticated_user)):
    _ensure_schema(db)
    engine = get_capabilities_engine(db)
    if req.action_id not in engine.actions:
        raise HTTPException(status_code=422, detail=f"Unknown capabilities-engine action_id '{req.action_id}'")
    policy_id = f"policy-{uuid.uuid4().hex[:10]}"
    db.conn.execute(
        """INSERT INTO autonomous_response_policies
           (policy_id, name, enabled, min_severity, attack_technique_keyword,
            action_id, action_payload_template, auto_approve, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (policy_id, req.name, req.enabled, req.min_severity, req.attack_technique_keyword,
         req.action_id, json.dumps(req.action_payload_template), req.auto_approve, user["username"]),
    )
    db.conn.commit()
    _audit(db, request, user, "create_policy", "success", policy_id, {"action_id": req.action_id})
    return {"policy_id": policy_id, "created": True}


@router.put("/policies/{policy_id}", dependencies=[require_permission("response:manage")])
async def update_policy(policy_id: str, req: PolicyUpdate, request: Request,
                         db: DuckDBManager = Depends(_db), user: dict = Depends(get_authenticated_user)):
    _ensure_schema(db)
    existing = db.conn.execute(
        "SELECT policy_id FROM autonomous_response_policies WHERE policy_id = ?", (policy_id,)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Policy not found")

    fields = req.model_dump(exclude_unset=True)
    if "action_id" in fields:
        engine = get_capabilities_engine(db)
        if fields["action_id"] not in engine.actions:
            raise HTTPException(status_code=422, detail=f"Unknown capabilities-engine action_id '{fields['action_id']}'")
    if "action_payload_template" in fields:
        fields["action_payload_template"] = json.dumps(fields["action_payload_template"])
    if not fields:
        return {"policy_id": policy_id, "updated": False, "reason": "no fields supplied"}

    set_clause = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = now()"
    db.conn.execute(
        f"UPDATE autonomous_response_policies SET {set_clause} WHERE policy_id = ?",
        (*fields.values(), policy_id),
    )
    db.conn.commit()
    _audit(db, request, user, "update_policy", "success", policy_id, fields)
    return {"policy_id": policy_id, "updated": True}


@router.delete("/policies/{policy_id}", dependencies=[require_permission("response:manage")])
async def delete_policy(policy_id: str, request: Request, db: DuckDBManager = Depends(_db),
                         user: dict = Depends(get_authenticated_user)):
    _ensure_schema(db)
    db.conn.execute("DELETE FROM autonomous_response_policies WHERE policy_id = ?", (policy_id,))
    db.conn.commit()
    _audit(db, request, user, "delete_policy", "success", policy_id)
    return {"policy_id": policy_id, "deleted": True}


# ══════════════════════════════════════════════════════════════════════════
# Evaluate — match a real finding against policies, execute via the
# capabilities engine
# ══════════════════════════════════════════════════════════════════════════

def _match_policy(policies: List[Dict[str, Any]], severity: str, attack_technique: str,
                   title: str, description: str) -> Optional[Dict[str, Any]]:
    """Deterministic match: highest min_severity first, first keyword hit
    wins within that tier — same explainable-over-opaque approach as
    response.py's _recommend_playbooks(). No fabricated confidence score."""
    text = f"{attack_technique} {title} {description}".lower()
    sev_rank = _rank(severity)
    candidates = [p for p in policies if p["enabled"] and sev_rank >= _rank(p["min_severity"])]
    candidates.sort(key=lambda p: _rank(p["min_severity"]), reverse=True)
    for p in candidates:
        kw = (p.get("attack_technique_keyword") or "").strip().lower()
        if not kw or kw in text:
            return p
    return None


@router.post("/evaluate")
async def evaluate(req: EvaluateRequest, request: Request, db: DuckDBManager = Depends(_db),
                    user: dict = Depends(get_authenticated_user)):
    """
    Evaluate one real finding against the configured policy set and, on a
    match, execute the mapped action via SecurityCapabilitiesEngine.
    execute(). HIGH/CRITICAL actions still return requires_approval +
    approval_id unless the matched policy is auto_approve — approve/deny
    that at the existing POST /api/capabilities/approve|deny/{approval_id}.
    """
    _ensure_schema(db)

    severity, title, description, attack_technique = req.severity, req.title, req.description, req.attack_technique
    if req.finding_id is not None:
        row = db.conn.execute(
            "SELECT severity, title, description, attack_technique FROM findings WHERE id = ?",
            (req.finding_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"finding {req.finding_id} not found")
        severity, title, description, attack_technique = row[0], row[1] or "", row[2] or "", row[3] or ""
    if not severity:
        raise HTTPException(status_code=422, detail="severity is required (either on the finding or in the request)")

    policy_rows = db.conn.execute("SELECT * FROM autonomous_response_policies").fetchall()
    cols = [d[0] for d in db.conn.description]
    policies = [dict(zip(cols, r)) for r in policy_rows]

    matched = _match_policy(policies, severity, attack_technique, title, description)
    event_id = str(uuid.uuid4())

    if not matched:
        db.conn.execute(
            """INSERT INTO autonomous_response_events
               (event_id, finding_id, target, policy_id, action_id, decision, engine_result, operator_id)
               VALUES (?, ?, ?, NULL, NULL, 'no_policy_matched', NULL, ?)""",
            (event_id, req.finding_id, req.target, req.operator_id),
        )
        db.conn.commit()
        return {"event_id": event_id, "decision": "no_policy_matched", "finding_id": req.finding_id,
                "severity": severity, "target": req.target}

    context = {"target": req.target, "title": title, "description": description,
               "attack_technique": attack_technique, "severity": severity,
               "finding_id": req.finding_id, "operator_id": req.operator_id}
    payload = _render_template(matched["action_payload_template"], context)

    engine = get_capabilities_engine(db)
    result = await engine.execute(matched["action_id"], payload, executor=req.operator_id,
                                   approved=bool(matched["auto_approve"]))

    if result.get("blocked"):
        decision = "blocked"
    elif result.get("requires_approval"):
        decision = "requires_approval"
    elif not result.get("ok", True):
        decision = "error"
    else:
        decision = "executed"

    db.conn.execute(
        """INSERT INTO autonomous_response_events
           (event_id, finding_id, target, policy_id, action_id, decision, engine_result, operator_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, req.finding_id, req.target, matched["policy_id"], matched["action_id"],
         decision, json.dumps(result, default=str), req.operator_id),
    )
    db.conn.commit()
    _audit(db, request, user, "evaluate_finding", decision, event_id,
           {"policy_id": matched["policy_id"], "action_id": matched["action_id"], "target": req.target})

    return {"event_id": event_id, "decision": decision, "policy_id": matched["policy_id"],
            "policy_name": matched["name"], "action_id": matched["action_id"],
            "finding_id": req.finding_id, "severity": severity, "target": req.target,
            "engine_result": result}


# ══════════════════════════════════════════════════════════════════════════
# Events — audit trail of past evaluations
# ══════════════════════════════════════════════════════════════════════════

@router.get("/events")
async def list_events(limit: int = 100, db: DuckDBManager = Depends(_db)):
    _ensure_schema(db)
    limit = max(1, min(limit, 500))
    rows = db.conn.execute(
        "SELECT * FROM autonomous_response_events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    cols = [d[0] for d in db.conn.description]
    events = []
    for r in rows:
        e = dict(zip(cols, r))
        try:
            e["engine_result"] = json.loads(e["engine_result"]) if e.get("engine_result") else None
        except Exception:
            pass
        events.append(e)
    return {"events": events, "count": len(events)}
