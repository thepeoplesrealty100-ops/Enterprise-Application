"""
backend/routers/cheatsheet.py
===============================
CheatSheet Library API — JAKAL v2.6.

The `admin_cheatsheet_library` frontend page had no live data source even
though the real content already existed server-side: 13 report modules +
43 tool cheat sheets (backend/gacyber_toolkit/CheatSheets/), queried
through the ontology layer in backend/payloads/cheatsheet_ontology.py, and
the response-procedure library in backend/payloads/playbook_library.py.
This router just exposes both as a browsable/searchable read API — no new
data model needed, it reuses the same CheatsheetOntology instance the AIP
payload generator (routers/aip.py) already drives.

Endpoints:
  GET /cheatsheet/stats             — corpus size, category counts
  GET /cheatsheet/categories        — list categories
  GET /cheatsheet/search            — resolve entries by phase/category/keyword
  GET /cheatsheet/entries/{entry_id} — full entry content
  GET /cheatsheet/graph             — ontology graph (objects + links)
  GET /cheatsheet/playbooks         — the response-procedure playbook library
  GET /cheatsheet/playbooks/{key}   — one playbook, full detail
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

try:
    from payloads.cheatsheet_ontology import CheatsheetOntology
    _ontology = CheatsheetOntology()
    from payloads.playbook_library import PLAYBOOKS
    CHEATSHEET_OK = True
    _ERR = None
except Exception as _e:  # noqa: BLE001
    CHEATSHEET_OK = False
    _ERR = str(_e)
    _ontology = None
    PLAYBOOKS = {}

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cheatsheet", tags=["cheatsheet"])


def _require():
    if not CHEATSHEET_OK:
        raise HTTPException(status_code=503, detail=f"CheatSheet library unavailable: {_ERR}")


@router.get("/stats")
async def stats():
    _require()
    return _ontology.stats()


@router.get("/categories")
async def categories():
    _require()
    return {"categories": _ontology.categories()}


@router.get("/search")
async def search(
    phase: Optional[str] = None,
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    include_non_executable: bool = Query(default=True, description="Include reference-only entries (e.g. social engineering docs)"),
    limit: int = Query(default=20, ge=1, le=200),
):
    _require()
    results = _ontology.resolve(
        phase=phase, category=category, keyword=keyword,
        include_non_executable=include_non_executable, limit=limit,
    )
    return {"count": len(results), "entries": results}


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: str):
    _require()
    entry = _ontology.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Cheatsheet entry not found")
    return entry


@router.get("/graph")
async def graph():
    _require()
    return _ontology.ontology_graph()


@router.get("/playbooks")
async def list_playbooks(category: Optional[str] = None):
    if category:
        return {"playbooks": [
            {"key": k, "name": p["name"], "category": p["category"], "phase": p.get("phase"),
             "estimated_hours": p.get("estimated_hours")}
            for k, p in PLAYBOOKS.items() if p.get("category") == category
        ]}
    return {"playbooks": [
        {"key": k, "name": p["name"], "category": p["category"], "phase": p.get("phase"),
         "estimated_hours": p.get("estimated_hours")}
        for k, p in PLAYBOOKS.items()
    ]}


@router.get("/playbooks/{key}")
async def get_playbook(key: str):
    playbook = PLAYBOOKS.get(key)
    if not playbook:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return playbook
