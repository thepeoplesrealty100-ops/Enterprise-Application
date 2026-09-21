"""
routers/capabilities.py — REST surface for the Security Capabilities Engine.

Exposes the seven blueprint domains (Fleet/RMM, Remote Access, Detect&Respond,
SOAR, Patch/Vuln, Dark Web, AI Safety Fabric) as a single, data-driven action
API. The frontend fetches /catalog to render the exact buttons, cogs, radial
selectors and sliders for each action.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from services.capabilities_engine import get_capabilities_engine

router = APIRouter(prefix="/api/capabilities", tags=["Security Capabilities"])


class ExecuteRequest(BaseModel):
    action_id: str
    payload: Dict[str, Any] = {}
    executor_id: str = "operator"
    approved: bool = False


class PromptScanRequest(BaseModel):
    prompt: str = ""


class RedactRequest(BaseModel):
    text: str = ""


class AuditRequest(BaseModel):
    response: str = ""
    context: str = ""


def _engine():
    # db_manager wired lazily; engine degrades gracefully without it.
    try:
        from database import get_db_manager
        return get_capabilities_engine(get_db_manager())
    except Exception:
        return get_capabilities_engine()


@router.get("/catalog")
async def catalog():
    """Full action catalog + category grouping — drives the data-driven UI."""
    e = _engine()
    return {"actions": e.catalog(), "by_category": e.catalog_by_category(),
            "count": len(e.actions)}


@router.get("/catalog/{category}")
async def catalog_category(category: str):
    e = _engine()
    return {"category": category, "actions": e.catalog_by_category().get(category, [])}


@router.post("/execute")
async def execute(req: ExecuteRequest):
    e = _engine()
    return await e.execute(req.action_id, req.payload, executor=req.executor_id,
                           approved=req.approved)


@router.get("/pending")
async def pending():
    return {"pending": _engine().pending_approvals()}


@router.post("/approve/{approval_id}")
async def approve(approval_id: str, executor_id: str = "operator"):
    return await _engine().approve(approval_id, executor=executor_id)


@router.post("/deny/{approval_id}")
async def deny(approval_id: str, executor_id: str = "operator"):
    return _engine().deny(approval_id, executor=executor_id)


def _db():
    from database import get_db_manager
    return get_db_manager()


@router.get("/inventory")
async def inventory():
    """Live counts across assets + all seven domains (drives the status view)."""
    from services import capabilities_seed as seed
    try:
        return seed.inventory(_db())
    except Exception as e:
        return {"error": str(e)}


@router.get("/data/{domain}")
async def domain_data(domain: str, limit: int = 100):
    """Seeded/operational rows for a domain (devices, alerts, CVEs, leaks,
    playbooks, sessions, RBAC, YARA, commands, human-risk, patch jobs)."""
    from services import capabilities_seed as seed
    try:
        return seed.get_domain_data(_db(), domain, limit=limit)
    except Exception as e:
        return {"error": str(e)}


@router.post("/seed")
async def reseed():
    """Idempotently ensure schema + seed data (safe to call anytime)."""
    from services import capabilities_seed as seed
    return seed.ensure_schema_and_seed(_db())


# ── AI Safety Fabric convenience endpoints (middleware-friendly) ──────────
@router.post("/aisafety/scan")
async def aisafety_scan(req: PromptScanRequest):
    return _engine().scan_prompt(req.prompt)


@router.post("/aisafety/redact")
async def aisafety_redact(req: RedactRequest):
    return _engine().redact_pii(req.text)


@router.post("/aisafety/audit")
async def aisafety_audit(req: AuditRequest):
    return _engine().audit_llm_response(req.response, req.context)
