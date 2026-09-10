"""
routers/assistant.py — JAKAL operator AI assistant with REAL tool-calling [#7]

The operator-console free-text box wires here. The assistant can actually
*invoke* the platform's real actions (threat-intel lookup, CVE scan, fleet
list, host isolation via the approval gate, dark-web recon, SOAR auto-triage)
rather than only chatting.

Two execution modes, same real tools:
  * LLM mode  — when an Anthropic key is stored in the Integrations vault, an
                agentic tool-calling loop (claude) decides which tools to call.
  * Router mode (no key) — a deterministic intent router maps the message to a
                tool and runs it, so the assistant still DOES real work with
                zero configuration.

Every tool call executes the same real backend as the UI; nothing is simulated.
"""
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/assistant", tags=["Operator Assistant"])

_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PKG_RE = re.compile(r"\b([A-Za-z0-9_.\-]+)[ =]+v?(\d[\w.\-]*)\b")


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── Tool definitions (Anthropic tool schema) ──────────────────────────────
TOOLS = [
    {"name": "threat_intel_lookup", "description": "Enrich an IP, domain, URL, or file hash against live threat feeds (Feodo, Tor, VirusTotal, AbuseIPDB, OTX). Use for 'is this IP malicious', reputation checks.",
     "input_schema": {"type": "object", "properties": {"indicator": {"type": "string"}}, "required": ["indicator"]}},
    {"name": "cve_scan", "description": "Scan software packages for known CVEs via live OSV.dev. Provide packages as name/version pairs.",
     "input_schema": {"type": "object", "properties": {"packages": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "version": {"type": "string"}}}}}, "required": ["packages"]}},
    {"name": "list_fleet", "description": "List managed endpoint agents and their online status.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "isolate_host", "description": "Network-isolate a managed endpoint (CRITICAL; routes through the human approval gate).",
     "input_schema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["agent_id"]}},
    {"name": "darkweb_recon", "description": "Check an email address for known breaches via Have I Been Pwned.",
     "input_schema": {"type": "object", "properties": {"identifier": {"type": "string"}}, "required": ["identifier"]}},
    {"name": "soar_auto_triage", "description": "Run the SOAR chain on an indicator: enrich -> (if malicious) isolate an endpoint -> open a ticket.",
     "input_schema": {"type": "object", "properties": {"indicator": {"type": "string"}, "agent_id": {"type": "string"}}, "required": ["indicator"]}},
]


async def _run_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool against the REAL backend."""
    from services.capabilities_engine import get_capabilities_engine
    from database import get_db_manager
    eng = get_capabilities_engine(get_db_manager())
    if name == "threat_intel_lookup":
        from services.threat_intel import lookup
        return lookup(args.get("indicator", ""))
    if name == "cve_scan":
        from services.vuln_scanner import scan_combined
        return scan_combined(args.get("packages", []))
    if name == "list_fleet":
        from routers.fleet_agent import list_agents
        return await list_agents()
    if name == "isolate_host":
        return await eng.execute("fleet:isolate_host", {"agent_id": args.get("agent_id"), "reason": args.get("reason", "assistant")})
    if name == "darkweb_recon":
        return await eng.execute("darkweb:run_recon", {"identifier": args.get("identifier", "")})
    if name == "soar_auto_triage":
        from routers.soar import auto_triage, TriageReq
        return await auto_triage(TriageReq(indicator=args.get("indicator", ""), agent_id=args.get("agent_id")))
    return {"error": f"unknown tool {name}"}


# ── Deterministic intent router (no-key fallback) ─────────────────────────
def _route_intent(msg: str) -> Optional[Dict[str, Any]]:
    m = msg.lower()
    email = _EMAIL_RE.search(msg)
    ip = _IP_RE.search(msg)
    if any(w in m for w in ("breach", "pwned", "leak", "dark web", "darkweb")) and email:
        return {"tool": "darkweb_recon", "args": {"identifier": email.group(0)}}
    if any(w in m for w in ("triage", "soar", "respond", "incident", "playbook")) and ip:
        agent = re.search(r"\b(agt-[\w]+|[A-Za-z0-9_-]*home)\b", msg)
        return {"tool": "soar_auto_triage", "args": {"indicator": ip.group(0), "agent_id": agent.group(0) if agent else None}}
    if any(w in m for w in ("fleet", "endpoints", "devices", "agents", "machines")):
        return {"tool": "list_fleet", "args": {}}
    if any(w in m for w in ("isolate", "contain", "quarantine host")):
        agent = re.search(r"\b(agt-[\w]+|[A-Za-z0-9_.-]*home)\b", msg)
        return {"tool": "isolate_host", "args": {"agent_id": agent.group(0) if agent else "UNKNOWN", "reason": "operator request"}}
    if any(w in m for w in ("cve", "vuln", "vulnerab", "outdated", "patch")):
        pkgs = [{"name": n, "version": v} for n, v in _PKG_RE.findall(msg)]
        if pkgs:
            return {"tool": "cve_scan", "args": {"packages": pkgs}}
    if ip or any(w in m for w in ("malicious", "reputation", "threat", "check this", "lookup", "look up", "intel")):
        target = ip.group(0) if ip else (msg.split()[-1] if msg.split() else "")
        return {"tool": "threat_intel_lookup", "args": {"indicator": target}}
    return None


def _summarize(tool: str, result: Dict[str, Any]) -> str:
    if tool == "threat_intel_lookup":
        return f"{result.get('indicator')} is **{result.get('verdict','?')}** (score {result.get('score',0)}). Flagged by: {', '.join(result.get('malicious_sources') or []) or 'none of the live feeds'}."
    if tool == "cve_scan":
        srcs = ", ".join(result.get("sources", [])) or "osv.dev/nvd"
        osv_n = (result.get("osv") or {}).get("vulnerable_packages", 0)
        nvd_n = (result.get("nvd") or {}).get("vulnerable_products", 0)
        return f"CVE scan ({srcs}): {result.get('critical',0)} critical, {result.get('high',0)} high across {osv_n+nvd_n} affected item(s)."
    if tool == "list_fleet":
        return f"{result.get('online',0)} of {result.get('count',0)} endpoint agent(s) online."
    if tool == "isolate_host":
        if result.get("requires_approval"):
            return f"Isolation of {result.get('action',{}).get('name','host') if isinstance(result.get('action'),dict) else 'host'} is **staged for approval** (approval_id {result.get('approval_id')}). Approve it in the console."
        return f"Isolation result: {result.get('status')}."
    if tool == "darkweb_recon":
        return f"Dark-web check: {result.get('status')} — {result.get('exposure_count',0)} exposure(s)." + (f" ({result.get('reason')})" if result.get('reason') else "")
    if tool == "soar_auto_triage":
        return f"SOAR triage on {result.get('indicator')}: verdict **{result.get('verdict')}**, ticket {result.get('ticket_id')} opened."
    return "Done."


class ChatReq(BaseModel):
    message: str
    executor_id: str = "operator"


@router.get("/status")
async def status():
    from services.secrets import get_secret
    return {"llm_configured": bool(get_secret("anthropic")), "tools": [t["name"] for t in TOOLS]}


@router.post("/chat")
async def chat(req: ChatReq):
    from services.secrets import get_secret
    key = get_secret("anthropic")
    if key:
        try:
            return await _chat_llm(req.message, key)
        except Exception as e:
            # fall back to the router if the LLM path errors
            fallback = await _chat_router(req.message)
            fallback["note"] = f"(LLM error: {e.__class__.__name__}; used intent router)"
            return fallback
    return await _chat_router(req.message)


async def _chat_router(message: str) -> Dict[str, Any]:
    intent = _route_intent(message)
    if not intent:
        return {"ok": True, "mode": "router", "reply": (
            "I can run: threat-intel lookups, CVE scans, fleet listing, host isolation, "
            "dark-web checks, and SOAR triage. Try: 'look up 162.243.103.246', "
            "'scan jinja2 2.10 for CVEs', 'list the fleet', or 'triage 1.2.3.4 on freddyhome'. "
            "Add an Anthropic key in Integrations for free-form AI chat."),
            "actions_taken": [], "at": _now()}
    result = await _run_tool(intent["tool"], intent["args"])
    return {"ok": True, "mode": "router", "reply": _summarize(intent["tool"], result),
            "actions_taken": [{"tool": intent["tool"], "input": intent["args"], "result": result}],
            "at": _now()}


async def _chat_llm(message: str, key: str) -> Dict[str, Any]:
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    model = "claude-3-5-sonnet-20241022"
    system = ("You are the JAKAL operator assistant. Use the provided tools to take real "
              "security actions on the operator's behalf. Prefer acting via tools over guessing. "
              "Keep replies concise and operational.")
    messages = [{"role": "user", "content": message}]
    actions: List[Dict[str, Any]] = []
    for _ in range(6):  # bounded agentic loop
        resp = client.messages.create(model=model, max_tokens=1024, system=system,
                                      tools=TOOLS, messages=messages)
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    result = await _run_tool(block.name, dict(block.input or {}))
                    actions.append({"tool": block.name, "input": block.input, "result": result})
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                         "content": json.dumps(result, default=str)[:6000]})
            messages.append({"role": "user", "content": tool_results})
            continue
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text")
        return {"ok": True, "mode": "llm", "reply": text or "(done)", "actions_taken": actions, "at": _now()}
    return {"ok": True, "mode": "llm", "reply": "Reached tool-call limit.", "actions_taken": actions, "at": _now()}
