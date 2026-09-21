"""
backend/payloads/aip_cheatsheet_engine.py
v3.0 Phase 4.1 -- Payload Intelligence / lightweight AIP CheatSheet.

A thin, prompt-driven lookup over this codebase's EXISTING playbook
catalog (payloads/playbook_library.py's PLAYBOOKS -- 8+ IR/threat-hunt/
red-team playbooks grounded in NIST SP 800-61 Rev. 3 / MITRE D3FEND /
NIST IR 8547, built in v2.7). Given a free-text prompt, ranks playbooks
by keyword overlap against their name/category/phase/mitre_tactics/
description/step titles/techniques, and returns the top matches with
their steps' commands as pre-populated scripts + a parameters summary
(techniques, tools, estimated_hours).

Deliberately does NOT introduce a new cheatsheet_playbooks DB table (the
spec marks that table optional). Duplicating PLAYBOOKS into a second,
DB-backed copy would create two sources of truth for the same content --
exactly what this schema's own comments elsewhere (see database.py's
role_permissions/v3.0 notes) warn against, and it would fork on the next
edit to either one. This queries the existing single source of truth
instead: "enhance the existing payload generator, don't replace it."

Primary use: ExploitAgent.get_enriched_approval_context() calls
recommend_for_payload() to give an approver a "why this payload" pointer
to the relevant playbook, if one exists (v3.0 Phase 4.1's actual stated
purpose -- richer approver context, not a general-purpose chatbot). The
POST /api/v3/aip/cheatsheet/chat endpoint (routers/aip_cheatsheet_router.py)
exposes query() directly for ad hoc lookups.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from payloads.playbook_library import PLAYBOOKS

_WORD_RE = re.compile(r"[a-zA-Z0-9_.]+")

# Recommended-scripts cap per match -- this is a pointer to the relevant
# playbook, not a full dump of it (the full playbook is already browsable
# via GET /api/cheatsheet/playbooks/{key}).
_MAX_RECOMMENDED_SCRIPTS = 10


class AIPCheatSheetEngine:
    """Thin prompt -> matching-playbooks lookup. No DB, no writes."""

    def __init__(self, playbooks: Optional[Dict[str, Dict[str, Any]]] = None):
        self._playbooks = playbooks if playbooks is not None else PLAYBOOKS

    @staticmethod
    def _tokenize(text: str) -> set:
        return {t.lower() for t in _WORD_RE.findall(text or "")}

    def _searchable_text(self, pb: Dict[str, Any]) -> str:
        parts = [
            pb.get("name", ""), pb.get("category", ""), pb.get("phase", ""),
            pb.get("description", ""), " ".join(pb.get("mitre_tactics", []) or []),
        ]
        for step in pb.get("steps", []) or []:
            parts.append(step.get("title", "") or "")
            parts.append(step.get("technique", "") or "")
        return " ".join(parts)

    def query(self, prompt: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Rank playbooks by token overlap with `prompt`. Returns
        [{playbook_key, name, category, phase, description, score,
        matched_terms, recommended_scripts, parameters}], highest score
        first. Empty list if the prompt has no tokens or nothing matches
        -- never raises."""
        prompt_tokens = self._tokenize(prompt)
        if not prompt_tokens:
            return []

        scored = []
        for key, pb in self._playbooks.items():
            haystack_tokens = self._tokenize(self._searchable_text(pb))
            matched = prompt_tokens & haystack_tokens
            if matched:
                scored.append((len(matched), matched, key, pb))
        scored.sort(key=lambda t: t[0], reverse=True)

        results = []
        for score, matched, key, pb in scored[:limit]:
            recommended_scripts: List[str] = []
            techniques, tools = set(), set()
            for step in pb.get("steps", []) or []:
                recommended_scripts.extend(step.get("commands", []) or [])
                if step.get("technique"):
                    techniques.add(step["technique"])
                tools.update(step.get("tools", []) or [])
            results.append({
                "playbook_key": key,
                "name": pb.get("name"),
                "category": pb.get("category"),
                "phase": pb.get("phase"),
                "description": pb.get("description"),
                "score": score,
                "matched_terms": sorted(matched),
                "recommended_scripts": recommended_scripts[:_MAX_RECOMMENDED_SCRIPTS],
                "parameters": {
                    "techniques": sorted(techniques),
                    "tools": sorted(tools),
                    "estimated_hours": pb.get("estimated_hours"),
                },
            })
        return results

    def recommend_for_payload(
        self, technique_id: Optional[str], phase: Optional[str], summary: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Best single playbook recommendation for one staged payload,
        built from its own technique_id/phase/summary -- the "why this
        payload" context for the Approval Gate. None if nothing scores."""
        prompt = " ".join(x for x in (technique_id, phase, summary) if x)
        matches = self.query(prompt, limit=1)
        return matches[0] if matches else None
