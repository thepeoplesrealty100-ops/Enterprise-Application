from fastapi import APIRouter, HTTPException
from pathlib import Path
import json
import asyncio
from typing import Any, Dict

from ..database import DuckDBManager
from ..llm_orchestrator import AgentOrchestrator


def get_router(db: DuckDBManager, orchestrator: AgentOrchestrator, config) -> APIRouter:
    router = APIRouter()
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = repo_root / "gacyber_toolkit" / "unified_fabric_manifest.json"
    cheatsheet_path = repo_root / "gacyber_toolkit" / "cheatsheet_data.json"

    def load_manifest() -> Dict[str, Any]:
        if not manifest_path.exists():
            return {"modules": []}
        with open(manifest_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def load_cheatsheets():
        if not cheatsheet_path.exists():
            return []
        with open(cheatsheet_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # normalize
        if isinstance(data, dict) and data.get("entries"):
            return data.get("entries")
        if isinstance(data, list):
            return data
        return []

    @router.get("/modules")
    async def list_modules():
        manifest = load_manifest()
        return {"modules": manifest.get("modules", [])}

    @router.get("/cheatsheets")
    async def list_cheatsheets(module: str = None, q: str = None):
        entries = load_cheatsheets()
        def match(e):
            if module:
                if e.get("module") != module and module not in (e.get("tags") or []):
                    return False
            if q:
                s = " ".join([str(e.get("title","")), str(e.get("content","")), " ".join(e.get("tags",[]))]).lower()
                if q.lower() not in s:
                    return False
            return True
        results = [
            {
                "id": e.get("id") or e.get("title"),
                "title": e.get("title"),
                "module": e.get("module"),
                "tags": e.get("tags"),
                "snippet": (e.get("content","")[:400] + "...") if e.get("content") and len(e.get("content"))>400 else e.get("content",""),
            }
            for e in entries if match(e)
        ]
        return {"count": len(results), "entries": results}

    @router.post("/draft_payload")
    async def draft_payload(payload: Dict[str, Any]):
        # payload: { module_key, cheatsheet_id, target_context, operator_id, extra_context }
        module_key = payload.get("module_key")
        target_context = payload.get("target_context", "")
        operator_id = payload.get("operator_id")
        cheatsheet_id = payload.get("cheatsheet_id")
        extra_context = payload.get("extra_context", "")

        if config.ENABLE_HUMAN_IN_LOOP and (not operator_id or operator_id == "system"):
            raise HTTPException(status_code=400, detail="operator_id required for human-in-loop operations")

        # find cheatsheet content
        cheatsheet = None
        if cheatsheet_id:
            for e in load_cheatsheets():
                if e.get("id") == cheatsheet_id or e.get("title") == cheatsheet_id:
                    cheatsheet = e
                    break
        # build prompt
        cheatsheet_text = cheatsheet.get("content") if cheatsheet else ""
        prompt = (
            "You are a security engineer assistant. Using the cheatsheet below (\n---\n" + (cheatsheet_text or "(no cheatsheet provided)") + "\n---\n) "
            "and the module context: %s, produce a safe, human-review-only payload template or checklist that an operator can use to perform the action. "
            "Do NOT produce executable commands or try to stage or run anything. Make the output descriptive, step-by-step, and safe for a manual operator.\n\n" 
            % (module_key or "unknown")
        )
        prompt += "Target context:\n" + str(target_context) + "\n\nExtra context:\n" + str(extra_context) + "\n\nRespond with a plain-text payload template."

        try:
            # call orchestrator's LLM methods
            if orchestrator.config.LLM_ENGINE == 'claude':
                result = await orchestrator._call_claude(prompt)
                model = orchestrator.config.CLAUDE_MODEL if hasattr(orchestrator.config, 'CLAUDE_MODEL') else orchestrator.config.CLAUDE_MODEL
            else:
                result = await orchestrator._call_ollama(prompt)
                model = orchestrator.config.OLLAMA_MODEL if hasattr(orchestrator.config, 'OLLAMA_MODEL') else orchestrator.config.OLLAMA_MODEL

            # persist audit log
            db.insert_log({
                "event": "draft_payload",
                "action": module_key,
                "status": "success",
                "operator_id": operator_id,
                "details": {"cheatsheet_id": cheatsheet_id, "model": model, "length": len(result or "")},
            })

            return {"draft": result, "model": model}
        except Exception as e:
            db.insert_log({
                "event": "draft_payload",
                "action": module_key,
                "status": "error",
                "operator_id": operator_id,
                "details": {"error": str(e)},
            })
            raise HTTPException(status_code=500, detail=str(e))

    return router
