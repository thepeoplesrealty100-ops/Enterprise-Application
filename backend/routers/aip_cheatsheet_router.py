"""
backend/routers/aip_cheatsheet_router.py
v3.0 Phase 4.1 -- prompt-driven playbook lookup, a thin layer over the
existing payloads/playbook_library.py PLAYBOOKS catalog (see
payloads/aip_cheatsheet_engine.py's module docstring for why this does
NOT introduce a new DB table). Complements, does not replace:
  - GET /api/aip/generate       (v2.2 ontology-bounded payload generator)
  - GET /api/cheatsheet/playbooks (v2.6 raw playbook browse API)

Endpoint:
  POST /chat -- {"prompt": "...", "limit": 5} -> ranked matching
                playbooks, each with pre-populated scripts (commands
                pulled straight from the playbook's own steps) and a
                parameters summary (techniques, tools, estimated_hours).
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from payloads.aip_cheatsheet_engine import AIPCheatSheetEngine

router = APIRouter(tags=["aip-cheatsheet-v3"])
_engine = AIPCheatSheetEngine()


class ChatRequest(BaseModel):
    prompt: str
    limit: int = 5


@router.post("/chat")
def chat(req: ChatRequest):
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    matches = _engine.query(prompt, limit=max(1, min(req.limit, 20)))
    return {"prompt": prompt, "count": len(matches), "matches": matches}
