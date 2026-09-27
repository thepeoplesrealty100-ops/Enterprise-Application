"""
backend/routers/report_builder.py
==================================
CPENT-style pentest report generator (JAKAL v2.8).

Turns the JSON a pentest run already produces (pentest_runs + the
assessment_reports snapshot that routers/reports.py's /aggregate persists,
built by security_agents/report_agent.py) into a real, client-attributable
deliverable — replacing the raw, unfillable EC-Council/CPENT curriculum
boilerplate ("[Organization's Logo]", "[Organization's Name]", ...) that
gacyber_toolkit/cheatsheet_data.json only ever displayed as static text.

Every section is optional (see GET /sections) so an operator can drop a
section they don't want in a given deliverable rather than hand-editing a
template after the fact. Executive Summary / Conclusion prose can be
LLM-drafted (services/llm_client.generate(), Claude or Ollama per-call via
`llm_engine`) from the *actual* findings data only — never fabricated; if
the LLM is unavailable this falls back to a plain templated paragraph
instead of failing the whole report.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from schemas import ReportBuilderRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-builder", tags=["report-builder"])

try:
    from database import get_db_manager
    from payloads.cheatsheet_ontology import CheatsheetOntology
    from services import doc_render
    from services.llm_client import LLMUnavailable, generate as llm_generate

    _db = get_db_manager()
    try:
        _ontology: Optional[CheatsheetOntology] = CheatsheetOntology()
    except Exception as exc:  # noqa: BLE001 — ontology is a nice-to-have section, not fatal
        logger.warning("report_builder: CheatsheetOntology unavailable: %s", exc)
        _ontology = None
    _READY = True
    _ERR: Optional[str] = None
except Exception as exc:  # noqa: BLE001
    _READY = False
    _ERR = str(exc)
    _db = None
    _ontology = None
    doc_render = None  # type: ignore[assignment]

    class LLMUnavailable(RuntimeError):  # type: ignore[no-redef]
        pass

    def llm_generate(*args, **kwargs):  # type: ignore[no-redef]
        raise LLMUnavailable("report_builder stack unavailable")


SECTION_DEFS: List[Dict[str, Any]] = [
    {"key": "cover", "title": "Cover Page", "removable": False},
    {"key": "executive_summary", "title": "Executive Summary", "removable": True},
    {"key": "scope_methodology", "title": "Scope & Methodology", "removable": True},
    {"key": "findings_summary", "title": "Findings Summary", "removable": True},
    {"key": "technical_findings", "title": "Detailed Technical Findings", "removable": True},
    {"key": "mitre_mapping", "title": "MITRE ATT&CK Mapping", "removable": True},
    {"key": "tools_commands", "title": "Tools & Commands Used", "removable": True},
    {"key": "conclusion", "title": "Conclusion & Recommendations", "removable": True},
]
_SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


def _require() -> None:
    if not _READY:
        raise HTTPException(status_code=503, detail=f"Report builder stack unavailable: {_ERR}")


def _get_pentest(scan_id: str) -> Optional[Dict[str, Any]]:
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
    cols = ["id", "target", "scan_type", "recon_results", "attack_mappings",
            "staged_exploits", "status", "created_at", "completed_at"]
    d = dict(zip(cols, rows[0]))
    for key in ("recon_results", "attack_mappings", "staged_exploits"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _get_assessment_report(pentest_id: int) -> Optional[Dict[str, Any]]:
    rows = _db.conn.execute(
        "SELECT content FROM assessment_reports WHERE pentest_id = ? ORDER BY id DESC LIMIT 1",
        (pentest_id,),
    ).fetchall()
    if not rows or not rows[0][0]:
        return None
    try:
        return json.loads(rows[0][0])
    except (json.JSONDecodeError, TypeError):
        return None


def _get_scope(scope_id: int) -> Optional[Dict[str, Any]]:
    rows = _db.conn.execute(
        "SELECT id, client_name, scope_definition, start_date, end_date FROM scopes WHERE id = ?",
        (scope_id,),
    ).fetchall()
    if not rows:
        return None
    cols = ["id", "client_name", "scope_definition", "start_date", "end_date"]
    return dict(zip(cols, rows[0]))


def _severity_counts(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {s: 0 for s in _SEVERITY_ORDER}
    for f in findings:
        sev = str(f.get("severity", "info")).lower()
        if sev in counts:
            counts[sev] += 1
    return counts


def _ai_or_fallback(system_prompt: str, user_prompt: str, engine: Optional[str], fallback: str) -> Dict[str, Any]:
    try:
        result = llm_generate(system_prompt, user_prompt, engine=engine, max_tokens=800)
        return {"text": result["text"].strip(), "ai_generated": True, "engine": result.get("engine")}
    except LLMUnavailable as exc:
        return {"text": fallback, "ai_generated": False, "note": f"AI narrative unavailable: {exc}"}


def _build_sections(req: ReportBuilderRequest, record: Dict[str, Any],
                     report_content: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    excluded = set(req.excluded_sections or [])
    findings = report_content.get("findings") or []
    counts = report_content.get("summary") or _severity_counts(findings)
    total = sum(counts.values())
    target = record.get("target") or "the target"
    client_name = req.organization_name or (scope or {}).get("client_name") or "the client"
    sections: List[Dict[str, Any]] = []

    # Cover — always included, it carries the client/report identity.
    cover_lines = [
        f"Report Title: {req.report_title}",
        f"Client / Organization: {client_name}",
        f"Contact: {req.contact_details or 'n/a'}",
        f"Penetration Tester: {req.tester_name}",
        f"Location: {req.location or 'n/a'}",
        f"Target: {target}",
        f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
    ]
    sections.append({"heading": "Cover Page", "body": "\n".join(cover_lines)})

    if "executive_summary" not in excluded:
        fallback = (
            f"This report summarizes a penetration test conducted against {target} on behalf of "
            f"{client_name}. {total} finding(s) were identified: "
            + ", ".join(f"{counts[s]} {s}" for s in _SEVERITY_ORDER if counts.get(s))
            + f"." if total else f"This report summarizes a penetration test conducted against {target} "
              f"on behalf of {client_name}. No findings were recorded for this engagement."
        )
        if req.ai_narrative:
            result = _ai_or_fallback(
                "You are a senior penetration tester writing the Executive Summary of a CPENT-style "
                "report for a client. Be concise and factual. Base every statement only on the finding "
                "data given; never invent findings, CVEs, or statistics not present in the data.",
                f"Client: {client_name}\nTarget: {target}\nSeverity counts: {json.dumps(counts)}\n"
                f"Findings (title/severity/source): "
                f"{json.dumps([{'title': f.get('title'), 'severity': f.get('severity'), 'source': f.get('source')} for f in findings])}\n\n"
                "Write a 2-paragraph Executive Summary covering overall risk posture and business impact. "
                "Plain text only, no markdown headers.",
                req.llm_engine, fallback,
            )
        else:
            result = {"text": fallback, "ai_generated": False}
        sections.append({"heading": "Executive Summary", "body": result["text"]})

    if "scope_methodology" not in excluded:
        scope_def = (scope or {}).get("scope_definition") or "As authorized under the engagement's rules of engagement."
        start = (scope or {}).get("start_date")
        end = (scope or {}).get("end_date")
        body = (
            f"Scope: {scope_def}\n"
            f"Engagement window: {start or 'n/a'} to {end or 'n/a'}\n\n"
            "Methodology: this engagement followed a staged approach — reconnaissance, enumeration, "
            "web application/service testing, exploitation (where authorized and staged through the "
            "platform's Human Approval Gate), and reporting — consistent with the CPENT "
            "(Certified Penetration Testing Professional) framework."
        )
        sections.append({"heading": "Scope & Methodology", "body": body})

    if "findings_summary" not in excluded:
        sections.append({
            "heading": "Findings Summary",
            "table": {
                "columns": ["Severity", "Count"],
                "rows": [[s.capitalize(), counts.get(s, 0)] for s in _SEVERITY_ORDER],
            },
        })

    if "technical_findings" not in excluded:
        if findings:
            rows = [
                [str(f.get("severity", "info")).upper(), f.get("title"), f.get("source"),
                 f.get("description") or "", f.get("remediation") or ""]
                for f in findings
            ]
            sections.append({
                "heading": "Detailed Technical Findings",
                "table": {"columns": ["Severity", "Title", "Source", "Description", "Remediation"], "rows": rows},
            })
        else:
            sections.append({"heading": "Detailed Technical Findings", "body": "No findings were recorded for this engagement."})

    if "mitre_mapping" not in excluded:
        mappings = report_content.get("mitre_attack_mappings") or []
        if mappings:
            rows = [[m.get("tactic"), f"{m.get('technique_id')} — {m.get('technique_name')}", m.get("finding")] for m in mappings]
            sections.append({
                "heading": "MITRE ATT&CK Mapping",
                "table": {"columns": ["Tactic", "Technique", "Finding"], "rows": rows},
            })
        else:
            sections.append({"heading": "MITRE ATT&CK Mapping", "body": "No MITRE ATT&CK mappings were recorded for this engagement."})

    if "tools_commands" not in excluded:
        if _ontology is not None:
            cmds: List[Dict[str, Any]] = []
            for phase in ("recon", "enum", "web"):
                try:
                    cmds.extend(_ontology.resolve_commands(phase=phase, target=target, limit_entries=4, commands_per_entry=3))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("resolve_commands(%s) failed: %s", phase, exc)
            if cmds:
                rows = [[c.get("phase"), c.get("command"), c.get("source_title")] for c in cmds[:24]]
                sections.append({
                    "heading": "Tools & Commands Used",
                    "table": {"columns": ["Phase", "Command", "Reference"], "rows": rows},
                })
            else:
                sections.append({"heading": "Tools & Commands Used", "body": "No cheatsheet-referenced commands matched this engagement's phases."})
        else:
            sections.append({"heading": "Tools & Commands Used", "body": "CheatSheet ontology unavailable — commands could not be resolved."})

    if "conclusion" not in excluded:
        fallback = (
            "Based on the findings above, it is recommended that the organization prioritize remediation "
            "of critical- and high-severity issues first, followed by a retest to validate fixes."
        )
        if req.ai_narrative:
            result = _ai_or_fallback(
                "You are a senior penetration tester writing the Conclusion of a CPENT-style report. "
                "Be concise. Base every recommendation only on the finding data given; never invent "
                "findings not present in the data.",
                f"Severity counts: {json.dumps(counts)}\nFindings: "
                f"{json.dumps([{'title': f.get('title'), 'severity': f.get('severity')} for f in findings])}\n\n"
                "Write a 1-paragraph Conclusion with prioritized remediation recommendations. "
                "Plain text only, no markdown headers.",
                req.llm_engine, fallback,
            )
        else:
            result = {"text": fallback, "ai_generated": False}
        sections.append({"heading": "Conclusion & Recommendations", "body": result["text"]})

    return sections


@router.get("/sections")
async def list_sections():
    """Available CPENT report sections and whether each can be excluded."""
    return {"sections": SECTION_DEFS}


@router.post("/generate")
async def generate_report(req: ReportBuilderRequest):
    _require()
    record = _get_pentest(req.scan_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Scan {req.scan_id!r} not found")

    report_content = _get_assessment_report(record["id"]) or {
        "target": record.get("target"),
        "generated_at": str(record.get("created_at")),
        "summary": {},
        "findings": [],
        "mitre_attack_mappings": record.get("attack_mappings") or [],
    }

    scope = _get_scope(req.scope_id) if req.scope_id is not None else None
    sections = _build_sections(req, record, report_content, scope)

    document = {
        "report_title": req.report_title,
        "scan_id": req.scan_id,
        "organization_name": req.organization_name or (scope or {}).get("client_name"),
        "contact_details": req.contact_details,
        "tester_name": req.tester_name,
        "location": req.location,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
    }

    _db.conn.execute(
        "INSERT INTO assessment_reports (pentest_id, report_type, content) VALUES (?, ?, ?)",
        (record["id"], "cpent_report", json.dumps(document, default=str)),
    )
    _db.conn.commit()

    fmt = (req.format or "json").lower()
    if fmt == "json":
        return document

    if fmt == "markdown":
        lines = [f"# {req.report_title}", ""]
        for sec in sections:
            lines.append(f"## {sec['heading']}")
            lines.append("")
            if sec.get("body"):
                lines.append(sec["body"])
                lines.append("")
            table = sec.get("table")
            if table and table.get("rows"):
                lines.append("| " + " | ".join(table["columns"]) + " |")
                lines.append("|" + "|".join(["---"] * len(table["columns"])) + "|")
                for row in table["rows"]:
                    lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
                lines.append("")
        return {"scan_id": req.scan_id, "format": "markdown", "content": "\n".join(lines)}

    if fmt in ("docx", "pdf"):
        subtitle = f"Prepared for {document['organization_name'] or 'the client'} — {record.get('target')}"
        try:
            if fmt == "docx":
                payload = doc_render.to_docx(req.report_title, subtitle, sections)
                media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ext = "docx"
            else:
                payload = doc_render.to_pdf(req.report_title, subtitle, sections)
                media_type = "application/pdf"
                ext = "pdf"
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=f"Document rendering dependency missing: {exc}")
        filename = f"pentest-report-{req.scan_id}.{ext}"
        return Response(
            content=payload, media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    raise HTTPException(status_code=400, detail=f"Unsupported format '{fmt}'. Choose: json, markdown, docx, pdf")


@router.get("/list")
async def list_generated_reports(limit: int = 50):
    _require()
    rows = _db.conn.execute(
        "SELECT ar.id, ar.pentest_id, pr.target, ar.created_at "
        "FROM assessment_reports ar JOIN pentest_runs pr ON pr.id = ar.pentest_id "
        "WHERE ar.report_type = 'cpent_report' ORDER BY ar.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"id": r[0], "scan_id": str(r[1]), "target": r[2], "created_at": str(r[3]) if r[3] is not None else None}
        for r in rows
    ]
