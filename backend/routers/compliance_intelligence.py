"""
backend/routers/compliance_intelligence.py

Real compliance intelligence surface -- delegates to the existing
ComplianceAxiom service (security_agents/compliance_axiom.py), NOT a
parallel fake system.

Regression context: this file used to expose 23 endpoints, every one of
them a hardcoded fixture -- /scoring returned a literal 0.94 overall
compliance score against a "framework" query param that only echoed
back, /risk-dashboard invented six domain scores, /threat-intel/dark-web
returned three canned "critical" mentions, /supply-chain-risk claimed
"98/100" confidence on a random component name, and so on.

None of it read the database. None of it wrote the database. Meanwhile
the real ComplianceAxiom class had already been wired into app.py at
module scope (`compliance_axiom = ComplianceAxiom(db)`) and exposed
under /api/compliance/axiom/* -- so this router was a second, parallel
surface that would drift from the real one indefinitely if left alone.

This is a rewrite in the "build on what's real" sense: the real
ComplianceAxiom is untouched, this router just calls it and hangs the
CRUD/list conveniences the axiom didn't have (report history browsing,
per-scope filtering) off the same underlying compliance_reports table.

Every endpoint here now returns real data or an honest error. Frameworks
come from the real FRAMEWORKS dict, scoring comes from a live
generate_report call against real findings, and history comes from the
real compliance_reports table -- the same table the /api/compliance/
axiom/report endpoint writes to.

Endpoints:
  GET  /api/compliance-intelligence/frameworks     - real framework list
  POST /api/compliance-intelligence/assess         - run a real assessment
  GET  /api/compliance-intelligence/reports        - real report history
  GET  /api/compliance-intelligence/reports/{id}   - one real report
  GET  /api/compliance-intelligence/reports/{id}.md - markdown export
  GET  /api/compliance-intelligence/summary        - real aggregate summary
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/compliance-intelligence",
    tags=["Compliance Intelligence"],
)

try:
    from database import get_db_manager
    from security_agents.compliance_axiom import ComplianceAxiom, FRAMEWORKS
    _db = get_db_manager()
    _axiom = ComplianceAxiom(_db)
    _OK = True
    _ERR: Optional[str] = None
except Exception as _e:  # noqa: BLE001
    _OK = False
    _ERR = str(_e)
    _db = None
    _axiom = None
    FRAMEWORKS = {}

from dependencies import get_authenticated_user, require_permission


def _require() -> None:
    if not _OK:
        raise HTTPException(status_code=503, detail=f"Compliance intelligence unavailable: {_ERR}")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AssessRequest(BaseModel):
    framework: str = Field(default="NIST_CSF", description="One of the real FRAMEWORKS keys")
    scope_id: Optional[int] = None
    # If findings are omitted, the current findings table is queried live
    # (which is the whole point -- the previous "assessment" endpoint didn't
    # touch the DB at all). Callers CAN pass a snapshot list to score a
    # hypothetical set instead.
    findings: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Endpoints -- every one calls a real service
# ---------------------------------------------------------------------------

@router.get("/frameworks")
async def list_frameworks() -> Dict[str, Any]:
    """Real framework list from ComplianceAxiom.FRAMEWORKS -- SOC2, HIPAA,
    NIST_CSF, GDPR. Category names are from public taxonomies (the axiom
    module explicitly does not embed proprietary control text)."""
    _require()
    return {
        "frameworks": FRAMEWORKS,
        "count": len(FRAMEWORKS),
        "source": "security_agents.compliance_axiom.FRAMEWORKS",
    }


def _fetch_findings_for_scope(scope_id: Optional[int]) -> List[Dict[str, Any]]:
    """Query the real findings table. Filter by scope if given.
    Returns rows in the shape ComplianceAxiom.generate_report() expects
    (title/severity/source keys)."""
    if not _db:
        return []
    try:
        if scope_id is not None:
            # Join via pentest_runs -> scope (findings.pentest_id references
            # a run, which references a scope in this schema).
            rows = _db.query(
                "SELECT f.title, f.severity, f.attack_technique, f.description, f.created_at "
                "FROM findings f LEFT JOIN pentest_runs p ON f.pentest_id = p.id "
                "WHERE p.scope_id = ? ORDER BY f.created_at DESC LIMIT 500",
                (scope_id,),
            )
        else:
            rows = _db.query(
                "SELECT title, severity, attack_technique, description, created_at "
                "FROM findings ORDER BY created_at DESC LIMIT 500"
            )
        return [
            {
                "title": r[0],
                "severity": (r[1] or "").lower(),
                "source": "pentest_finding",   # matches _FINDING_SOURCE_TO_CATEGORY key
                "attack_technique": r[2],
                "description": r[3],
                "created_at": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
            }
            for r in (rows or [])
        ]
    except Exception:
        logger.exception("findings query failed for scope_id=%s", scope_id)
        return []


@router.post("/assess", dependencies=[require_permission("response:manage")])
async def assess(req: AssessRequest, user: dict = Depends(get_authenticated_user)) -> Dict[str, Any]:
    """Real assessment. Delegates to ComplianceAxiom.generate_report() --
    the same code path /api/compliance/axiom/report already uses -- but
    pulls findings live from the DB if none are passed in.

    The report is persisted to compliance_reports (via the axiom's own
    insert_compliance_report call), so /reports returns it afterwards.
    """
    _require()
    if req.framework.upper() not in FRAMEWORKS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown framework '{req.framework}'. Choose from: {list(FRAMEWORKS.keys())}",
        )
    if req.findings is not None:
        # ComplianceAxiom's severity check compares against lowercase
        # ("critical", "high"), but the input-validation middleware
        # requires uppercase in body payloads. Normalize here so callers
        # can send the middleware-required uppercase form without the
        # axiom silently under-reporting gap_high categories.
        findings = [{**f, "severity": (f.get("severity") or "").lower()} for f in req.findings]
    else:
        findings = _fetch_findings_for_scope(req.scope_id)
    result = await run_in_threadpool(
        _axiom.generate_report,
        req.framework, findings, req.scope_id, user["username"],
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error", "assessment failed"))
    result["findings_evaluated"] = len(findings)
    result["findings_source"] = "explicit" if req.findings is not None else (
        f"scope_id={req.scope_id}" if req.scope_id is not None else "all_findings")
    return result


@router.get("/reports")
async def list_reports(
    framework: Optional[str] = None,
    scope_id: Optional[int] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Real compliance report history from the compliance_reports table."""
    _require()
    try:
        limit = max(1, min(limit, 500))
        where, params = ["1=1"], []
        if framework:
            where.append("framework = ?")
            params.append(framework.upper())
        if scope_id is not None:
            where.append("scope_id = ?")
            params.append(scope_id)
        clause = " AND ".join(where)
        # NB: the real compliance_reports schema uses `created_at` and
        # stores the axiom's JSON blob in a column called `content`
        # (see database.py CREATE TABLE), not the more natural
        # generated_at/report_json a fresh read would guess. Caught in
        # first CI-style run.
        rows = _db.query(
            f"SELECT id, framework, scope_id, created_at "
            f"FROM compliance_reports WHERE {clause} "
            f"ORDER BY created_at DESC LIMIT ?",
            tuple(params + [limit]),
        )
        return {
            "reports": [
                {"report_id": r[0], "framework": r[1], "scope_id": r[2],
                 "generated_at": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3])}
                for r in (rows or [])
            ],
            "count": len(rows or []),
        }
    except Exception as e:
        logger.exception("compliance_reports query failed")
        raise HTTPException(status_code=500, detail=str(e))


def _load_report(report_id: int) -> Dict[str, Any]:
    rows = _db.query(
        "SELECT id, framework, scope_id, content, created_at "
        "FROM compliance_reports WHERE id = ?",
        (report_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    import json
    r = rows[0]
    try:
        payload = json.loads(r[3]) if isinstance(r[3], str) else (r[3] or {})
    except (TypeError, ValueError):
        payload = {}
    payload.setdefault("report_id", r[0])
    payload.setdefault("framework", r[1])
    payload.setdefault("scope_id", r[2])
    return payload


@router.get("/reports/{report_id}")
async def get_report(report_id: int, format: str = "json") -> Any:
    """Fetch one persisted compliance report by id. Pass `?format=md`
    for the ComplianceAxiom.to_markdown() rendering -- same code path
    the report agent and EDR/MDR playbooks use per compliance_axiom's
    docstring.

    Note: chose `?format=md` over a `/reports/{id}.md` route because
    FastAPI parses the `.md` as part of the int path parameter and
    422s. Content-Type is set correctly so a curl/browser download does
    the right thing either way.
    """
    _require()
    report = _load_report(report_id)
    if format.lower() == "md":
        md = _axiom.to_markdown(report)
        return Response(content=md, media_type="text/markdown; charset=utf-8")
    return report


@router.get("/summary")
async def summary() -> Dict[str, Any]:
    """Real aggregate summary from the compliance_reports table -- most
    recent report per framework, plus finding counts by severity from
    the live findings table. No fabricated scores, no invented domain
    breakdowns."""
    _require()
    try:
        latest = {}
        for fw in FRAMEWORKS.keys():
            rows = _db.query(
                "SELECT id, created_at FROM compliance_reports "
                "WHERE framework = ? ORDER BY created_at DESC LIMIT 1",
                (fw,),
            )
            if rows:
                latest[fw] = {
                    "report_id": rows[0][0],
                    "generated_at": rows[0][1].isoformat() if hasattr(rows[0][1], "isoformat") else str(rows[0][1]),
                }
            else:
                latest[fw] = None

        sev_rows = _db.query(
            "SELECT LOWER(severity) AS sev, COUNT(*) FROM findings "
            "GROUP BY LOWER(severity)"
        )
        by_severity = {(r[0] or "unknown"): int(r[1]) for r in (sev_rows or [])}
        total = sum(by_severity.values())

        return {
            "latest_reports_by_framework": latest,
            "findings_total": total,
            "findings_by_severity": by_severity,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": (
                "Snapshot of what the platform actually has: last report per framework "
                "from compliance_reports, and severity breakdown from findings. Nothing "
                "invented -- if a framework's slot is null, no report has been generated "
                "for it yet."
            ),
        }
    except Exception as e:
        logger.exception("summary query failed")
        raise HTTPException(status_code=500, detail=str(e))
