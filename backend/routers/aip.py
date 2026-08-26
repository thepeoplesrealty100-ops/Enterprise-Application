"""
backend/routers/aip.py
======================
AIP Payload Generator API router (JAKAL v2.2).

Ontology-driven payload generation that interweaves the pre-populated MITRE
payloads with the GACyber CheatSheet Library. Every generation is
authorization-gated, ontology-bounded, and PQC-audit-signed.

Endpoints:
  GET   /aip/status              — generator + ontology status
  GET   /aip/ontology            — cheatsheet ontology graph (objects + links)
  GET   /aip/cheatsheets         — resolve cheatsheet entries by phase/category/keyword
  GET   /aip/cheatsheet/{id}     — full cheatsheet entry content
  POST  /aip/generate            — generate a bounded payload plan for one phase
  POST  /aip/engagement          — generate bounded plans across all phases
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel

try:
    from payloads.aip_payload_generator import AIPPayloadGenerator
    from payloads.cheatsheet_ontology import CheatsheetOntology
    from database import DuckDBManager
    _db: Optional[DuckDBManager] = DuckDBManager()
    _aip = AIPPayloadGenerator(db=_db)
    _ontology = _aip.ontology
    AIP_OK = True
except Exception as _e:
    AIP_OK = False
    _AIP_ERR = str(_e)
    _db = None
    _aip = None
    _ontology = None

# Import AuthorizationError for clean 403 mapping
try:
    from tools.authorization import AuthorizationError
except Exception:
    class AuthorizationError(Exception):
        pass


class GenerateRequest(BaseModel):
    target: str
    phase: str
    operator_id: str = "system"
    domain: str = ""
    use_llm: bool = False
    max_cheatsheet_entries: int = 8

class EngagementRequest(BaseModel):
    target: str
    operator_id: str = "system"
    domain: str = ""
    phases: Optional[List[str]] = None


router = APIRouter(prefix="/aip", tags=["aip-payload-generator"])


def _require():
    if not AIP_OK:
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"AIP generator unavailable: {_AIP_ERR}")


@router.get("/status")
def aip_status():
    """AIP generator + cheatsheet ontology status."""
    _require()
    return _aip.status()


@router.get("/ontology")
def aip_ontology():
    """Cheatsheet ontology graph (objects + links) — phases, categories, entries."""
    _require()
    return _aip.ontology_graph()


@router.get("/cheatsheets")
def resolve_cheatsheets(
    phase: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Resolve cheatsheet entries by phase, category, or keyword (executable only)."""
    _require()
    entries = _ontology.resolve(phase=phase, category=category, keyword=keyword, limit=limit)
    return {"count": len(entries), "entries": entries}


@router.get("/cheatsheet/{entry_id}")
def get_cheatsheet(entry_id: str, include_commands: bool = Query(True)):
    """Full cheatsheet entry, optionally with extracted command templates."""
    _require()
    entry = _ontology.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Cheatsheet '{entry_id}' not found")
    result = dict(entry)
    if include_commands:
        result["commands"] = _ontology.extract_commands(entry["content"], max_commands=25)
    return result


@router.post("/generate", status_code=http_status.HTTP_201_CREATED)
def generate_payloads(req: GenerateRequest):
    """
    Generate an ontology-bounded, authorization-gated, PQC-signed payload plan
    for one PTES phase. Interweaves MITRE payloads + real cheatsheet commands.
    """
    _require()
    try:
        plan = _aip.generate(
            target=req.target, phase=req.phase, operator_id=req.operator_id,
            domain=req.domain, use_llm=req.use_llm,
            max_cheatsheet_entries=req.max_cheatsheet_entries,
        )
    except AuthorizationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return plan


@router.post("/engagement", status_code=http_status.HTTP_201_CREATED)
def generate_engagement(req: EngagementRequest):
    """Generate ontology-bounded plans across all (or given) phases for a target."""
    _require()
    try:
        engagement = _aip.generate_engagement(
            target=req.target, operator_id=req.operator_id,
            domain=req.domain, phases=req.phases,
        )
    except AuthorizationError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return engagement
