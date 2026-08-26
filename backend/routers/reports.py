"""
backend/routers/reports.py
FastAPI router for report aggregation and export.
"""

from fastapi import APIRouter, HTTPException

from schemas import (
    AggregateReportRequest,
    ReportExportRequest,
    StatusResponse,
)
from repository import scan_repo
from wrappers import ReportsWrapper

router = APIRouter(prefix="/reports", tags=["reports"])

reporter = ReportsWrapper()


@router.post("/aggregate")
async def aggregate_report(req: AggregateReportRequest):
    """
    Aggregate a list of tool results for a given scan_id into a unified report.
    Stores the report back in the scan repository if the scan exists.
    """
    report = reporter.generate_summary(req.scan_id, req.results)

    # Persist into repository if the scan record exists
    existing = scan_repo.get_scan(req.scan_id)
    if existing:
        scan_repo.update_scan_status(req.scan_id, existing["status"], report=report)

    return report


@router.get("/export/{scan_id}")
async def export_report(scan_id: str, req: ReportExportRequest = None):
    """Export a completed scan report in JSON or Markdown format."""
    record = scan_repo.get_scan(scan_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id!r} not found")

    report = record.get("report")
    if not report:
        raise HTTPException(
            status_code=404,
            detail="No report available — scan may still be running",
        )

    fmt = (req.format if req else "json").lower()

    if fmt == "json":
        return report

    elif fmt == "markdown":
        lines = [
            f"# JAKAL Pentest Report — {scan_id}",
            "",
            f"**Generated:** {report.get('generated_at', 'n/a')}  ",
            f"**Targets:** {', '.join(report.get('targets', []))}  ",
            f"**Tools run:** {', '.join(report.get('tools_run', []))}  ",
            f"**Total findings:** {report.get('total_findings', 0)}  ",
            f"**Risk score:** {report.get('risk_score', 0)}  ",
            "",
            "## High-Priority Findings",
            "",
        ]
        for finding in report.get("high_priority", []):
            lines.append(
                f"- **{finding.get('severity', '?').upper()}** — "
                f"{finding.get('name', finding.get('template-id', 'unknown'))}"
            )
        if not report.get("high_priority"):
            lines.append("_None_")

        return {"scan_id": scan_id, "format": "markdown", "content": "\n".join(lines)}

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{fmt}'. Choose: json, markdown",
        )


@router.get("/list", response_model=list)
async def list_reports(operator_id: str = None):
    """List all scan records, optionally filtered by operator_id."""
    scans = scan_repo.list_scans(operator_id=operator_id)
    return [
        {
            "scan_id":    s["scan_id"],
            "target":     s["target"],
            "status":     s["status"],
            "created_at": s["created_at"],
        }
        for s in scans
    ]
