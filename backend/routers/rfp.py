"""
backend/routers/rfp.py
=======================
RFP (Request for Proposal) response builder (JAKAL v2.8).

The `rfp_responses` DuckDB table and its DB-manager methods
(insert_rfp_response/list_rfp_responses) were fully built but never exposed
over the API — this router is that missing surface. It lets an operator
save reusable proposal boilerplate per client (methodology, tools, timeline,
pricing, insurance) and export it as a client-ready document, optionally
with the configured LLM (Claude or Ollama, per-call via `llm_engine`)
drafting any fields left blank.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from schemas import RfpCreateRequest, RfpExportRequest, RfpUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rfp", tags=["rfp"])

try:
    from database import get_db_manager
    from services import doc_render
    from services.llm_client import LLMUnavailable, generate as llm_generate

    _db = get_db_manager()
    _READY = True
    _ERR: Optional[str] = None
except Exception as exc:  # noqa: BLE001
    _READY = False
    _ERR = str(exc)
    _db = None
    doc_render = None  # type: ignore[assignment]

    class LLMUnavailable(RuntimeError):  # type: ignore[no-redef]
        pass

    def llm_generate(*args, **kwargs):  # type: ignore[no-redef]
        raise LLMUnavailable("rfp stack unavailable")


def _require() -> None:
    if not _READY:
        raise HTTPException(status_code=503, detail=f"RFP stack unavailable: {_ERR}")


def _row_to_dict(row) -> Dict[str, Any]:
    cols = ["id", "client_name", "methodology", "tools_list", "timeline",
            "pricing", "insurance_statement", "sample_report_path", "created_at"]
    d = dict(zip(cols, row))
    if isinstance(d.get("tools_list"), str):
        try:
            d["tools_list"] = json.loads(d["tools_list"])
        except (json.JSONDecodeError, TypeError):
            d["tools_list"] = []
    return d


def _get_rfp(rfp_id: int) -> Optional[Dict[str, Any]]:
    rows = _db.conn.execute(
        "SELECT id, client_name, methodology, tools_list, timeline, pricing, "
        "insurance_statement, sample_report_path, created_at "
        "FROM rfp_responses WHERE id = ?",
        (rfp_id,),
    ).fetchall()
    if not rows:
        return None
    return _row_to_dict(rows[0])


def _ai_draft(field: str, client_name: str, engine: Optional[str]) -> Optional[str]:
    prompts = {
        "methodology": (
            "Write a concise (1 paragraph) penetration-testing methodology summary "
            "suitable for an RFP response, covering reconnaissance, enumeration, "
            "exploitation (with client authorization), and reporting."
        ),
        "timeline": "Propose a concise, typical engagement timeline (in weeks) for a standard penetration test, as 2-3 sentences.",
        "pricing": "Write a short, generic placeholder pricing statement (no real numbers) noting that final pricing depends on scope, to be confirmed after scoping.",
        "insurance_statement": "Write a short, generic statement that the firm carries professional liability / cyber errors & omissions insurance, placeholder wording to be confirmed with real policy details.",
    }
    try:
        result = llm_generate(
            "You are drafting boilerplate content for a cybersecurity firm's RFP (Request for "
            "Proposal) response. Be generic and professional; do not invent specific figures, "
            "policy numbers, or dates.",
            f"Client: {client_name}\n\n{prompts[field]}",
            engine=engine, max_tokens=300,
        )
        return result["text"].strip()
    except LLMUnavailable as exc:
        logger.info("rfp AI draft skipped for %s: %s", field, exc)
        return None


@router.post("")
async def create_rfp(req: RfpCreateRequest):
    _require()
    methodology = req.methodology
    timeline = req.timeline
    pricing = req.pricing
    insurance_statement = req.insurance_statement

    if req.ai_draft:
        if not methodology:
            methodology = _ai_draft("methodology", req.client_name, req.llm_engine)
        if not timeline:
            timeline = _ai_draft("timeline", req.client_name, req.llm_engine)
        if not pricing:
            pricing = _ai_draft("pricing", req.client_name, req.llm_engine)
        if not insurance_statement:
            insurance_statement = _ai_draft("insurance_statement", req.client_name, req.llm_engine)

    record = {
        "client_name": req.client_name,
        "methodology": methodology,
        "tools_list": req.tools_list,
        "timeline": timeline,
        "pricing": pricing,
        "insurance_statement": insurance_statement,
        "sample_report_path": req.sample_report_path,
    }
    new_id = _db.insert_rfp_response(record)
    return _get_rfp(new_id) if new_id is not None else record


@router.get("")
async def list_rfps():
    _require()
    return _db.list_rfp_responses()


@router.get("/{rfp_id}")
async def get_rfp(rfp_id: int):
    _require()
    record = _get_rfp(rfp_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"RFP response {rfp_id} not found")
    return record


@router.put("/{rfp_id}")
async def update_rfp(rfp_id: int, req: RfpUpdateRequest):
    _require()
    if _get_rfp(rfp_id) is None:
        raise HTTPException(status_code=404, detail=f"RFP response {rfp_id} not found")

    updates = req.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return _get_rfp(rfp_id)

    set_clauses = []
    params: List[Any] = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = ?")
        params.append(json.dumps(value) if field == "tools_list" else value)
    params.append(rfp_id)

    _db.conn.execute(f"UPDATE rfp_responses SET {', '.join(set_clauses)} WHERE id = ?", params)
    _db.conn.commit()
    return _get_rfp(rfp_id)


@router.delete("/{rfp_id}")
async def delete_rfp(rfp_id: int):
    _require()
    if _get_rfp(rfp_id) is None:
        raise HTTPException(status_code=404, detail=f"RFP response {rfp_id} not found")
    _db.conn.execute("DELETE FROM rfp_responses WHERE id = ?", (rfp_id,))
    _db.conn.commit()
    return {"status": "deleted", "id": rfp_id}


@router.post("/{rfp_id}/export")
async def export_rfp(rfp_id: int, req: RfpExportRequest):
    _require()
    record = _get_rfp(rfp_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"RFP response {rfp_id} not found")

    tools = record.get("tools_list") or []
    sections = [
        {
            "heading": "Introduction",
            "body": f"This proposal is submitted by our team in response to the Request for Proposal "
                    f"from {record['client_name']} for penetration testing / security assessment services.",
        },
        {"heading": "Proposed Methodology", "body": record.get("methodology") or "To be confirmed during scoping."},
        {
            "heading": "Tools & Technologies",
            "body": ", ".join(tools) if tools else "To be confirmed based on final scope.",
        },
        {"heading": "Proposed Timeline", "body": record.get("timeline") or "To be confirmed during scoping."},
        {"heading": "Pricing", "body": record.get("pricing") or "To be confirmed during scoping."},
        {"heading": "Insurance & Liability", "body": record.get("insurance_statement") or "Available upon request."},
    ]
    if record.get("sample_report_path"):
        sections.append({"heading": "Sample Report", "body": f"A sample report is available: {record['sample_report_path']}"})

    fmt = (req.format or "docx").lower()
    title = f"Proposal — {record['client_name']}"

    if fmt == "json":
        return {"client_name": record["client_name"], "sections": sections}

    if fmt == "markdown":
        lines = [f"# {title}", ""]
        for sec in sections:
            lines.append(f"## {sec['heading']}")
            lines.append("")
            lines.append(sec["body"])
            lines.append("")
        return {"client_name": record["client_name"], "format": "markdown", "content": "\n".join(lines)}

    if fmt in ("docx", "pdf"):
        try:
            if fmt == "docx":
                payload = doc_render.to_docx(title, "Penetration Testing Services Proposal", sections)
                media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ext = "docx"
            else:
                payload = doc_render.to_pdf(title, "Penetration Testing Services Proposal", sections)
                media_type = "application/pdf"
                ext = "pdf"
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=f"Document rendering dependency missing: {exc}")
        filename = f"rfp-response-{rfp_id}.{ext}"
        return Response(
            content=payload, media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    raise HTTPException(status_code=400, detail=f"Unsupported format '{fmt}'. Choose: json, markdown, docx, pdf")
