"""
backend/routers/reports.py
==========================
Report aggregation and export — DuckDB-backed (JAKAL v2.5).

Replaces the old in-memory scan_repo path.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from schemas import AggregateReportRequest, ReportExportRequest

router = APIRouter(prefix="/reports", tags=["reports"])

try:
    from database import DuckDBManager
    from wrappers import ReportsWrapper

    _db = DuckDBManager()
    _reporter = ReportsWrapper()
    _READY = True
    _ERR: Optional[str] = None
except Exception as exc:  # noqa: BLE001
    _READY = False
    _ERR = str(exc)
    _db = None
    _reporter = None


def _require() -> None:
    if not _READY:
        raise HTTPException(status_code=503, detail=f"Reports stack unavailable: {_ERR}")


def _row_to_dict(cols: List[str], row: tuple) -> Dict[str, Any]:
    d = dict(zip(cols, row))
    for key in ("recon_results", "attack_mappings", "staged_exploits", "content"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _get_pentest(scan_id: str) -> Optional[Dict[str, Any]]:
    """Resolve scan_id as pentest_runs.id (int as string) or not found."""
    try:
        pid = int(scan_id)
    except (TypeError, ValueError):
        return None
    rows = _db.conn.execute(
        "SELECT id, target, scan_type, recon_results, attack_mappings, "
        "staged_exploits, status, created_at, completed_at "
        "FROM pentest_runs WHERE id = ?",
        (pid,),
    ).fetchall()
    if not rows:
        return None
    cols = [
        "id", "target", "scan_type", "recon_results", "attack_mappings",
        "staged_exploits", "status", "created_at", "completed_at",
    ]
    return _row_to_dict(cols, rows[0])


def _get_assessment_report(pentest_id: int) -> Optional[Dict[str, Any]]:
    rows = _db.conn.execute(
        "SELECT id, pentest_id, report_type, content, created_at "
        "FROM assessment_reports WHERE pentest_id = ? ORDER BY id DESC LIMIT 1",
        (pentest_id,),
    ).fetchall()
    if not rows:
        return None
    cols = ["id", "pentest_id", "report_type", "content", "created_at"]
    return _row_to_dict(cols, rows[0])


@router.post("/aggregate")
async def aggregate_report(req: AggregateReportRequest):
    """Aggregate tool results into a unified report and persist to DuckDB."""
    _require()
    report = _reporter.generate_summary(req.scan_id, req.results)

    try:
        pid = int(req.scan_id)
    except (TypeError, ValueError):
        pid = None

    if pid is not None:
        _db.conn.execute(
            "INSERT INTO assessment_reports (pentest_id, report_type, content) VALUES (?, ?, ?)",
            (pid, "aggregate", json.dumps(report, default=str)),
        )
        _db.conn.commit()

    return report


@router.get("/export/{scan_id}")
async def export_report(scan_id: str, format: str = Query("json")):
    """Export a completed pentest report as JSON or Markdown."""
    _require()
    record = _get_pentest(scan_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id!r} not found")

    stored = _get_assessment_report(int(scan_id))
    report = (stored or {}).get("content") if stored else None
    if not report:
        # Minimal report from pentest_runs alone
        report = {
            "scan_id": scan_id,
            "target": record.get("target"),
            "status": record.get("status"),
            "recon_results": record.get("recon_results") or {},
            "attack_mappings": record.get("attack_mappings") or [],
            "generated_at": str(record.get("created_at")),
            "targets": [record.get("target")] if record.get("target") else [],
            "tools_run": [],
            "total_findings": 0,
            "risk_score": 0,
            "high_priority": [],
        }

    fmt = (format or "json").lower()

    if fmt == "json":
        return report

    if fmt == "markdown":
        lines = [
            f"# JAKAL Pentest Report — {scan_id}",
            "",
            f"**Generated:** {report.get('generated_at', 'n/a')}  ",
            f"**Targets:** {', '.join(report.get('targets', []) or [report.get('target') or 'n/a'])}  ",
            f"**Tools run:** {', '.join(report.get('tools_run', []) or [])}  ",
            f"**Total findings:** {report.get('total_findings', 0)}  ",
            f"**Risk score:** {report.get('risk_score', 0)}  ",
            "",
            "## High-Priority Findings",
            "",
        ]
        for finding in report.get("high_priority", []) or []:
            lines.append(
                f"- **{str(finding.get('severity', '?')).upper()}** — "
                f"{finding.get('name', finding.get('template-id', 'unknown'))}"
            )
        if not report.get("high_priority"):
            lines.append("_None_")
        return {"scan_id": scan_id, "format": "markdown", "content": "\n".join(lines)}

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported format '{fmt}'. Choose: json, markdown",
    )


@router.get("/list")
async def list_reports(limit: int = Query(50, ge=1, le=500)):
    """List recent pentest runs (report index)."""
    _require()
    rows = _db.conn.execute(
        "SELECT id, target, status, created_at FROM pentest_runs "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "scan_id": str(r[0]),
            "target": r[1],
            "status": r[2],
            "created_at": str(r[3]) if r[3] is not None else None,
        }
        for r in rows
    ]
