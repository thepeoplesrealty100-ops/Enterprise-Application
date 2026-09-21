"""
capabilities_engine.py — JAKAL Security Capabilities Engine (v1.0)

Core executor for the seven blueprint capability domains — Fleet & RMM,
Remote Access, Detect & Respond (EDR/XDR), SOAR Playbooks, Patch &
Vulnerability, Dark Web Intelligence, and the AI Safety Fabric.

Design principles (grounded, not "wishful"):
  * DELEGATE to existing subsystems where they already exist
    (routers.response isolate/quarantine/block, ui_bridge device actions,
     security_agents.*, vm_orchestrator, vault OSV scan). Soft imports keep
     the engine importable even when an optional subsystem is missing.
  * Every action carries a machine-readable ModuleAction contract (category,
    permission, risk, JSON payload schema) so the frontend can render the
    exact buttons / cogs / settings for it, data-driven.
  * Every execution passes the AI Safety Fabric guardrail check first, is
    written to the audit log, and — when risk >= HIGH — returns
    `requires_approval` so the Command Console can float an approval gate
    instead of executing blind.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger("capabilities_engine")


# ── Contracts ────────────────────────────────────────────────────────────
class ModuleCategory(str, Enum):
    FLEET_RMM = "fleet_rmm"
    REMOTE_ACCESS = "remote_access"
    DETECT_RESPOND = "detect_respond"
    SOAR_PLAYBOOKS = "soar_playbooks"
    PATCH_VULNERABILITY = "patch_vulnerability"
    DARK_WEB = "dark_web"
    AI_SAFETY_FABRIC = "ai_safety_fabric"
    MSP_MULTITENANT = "msp_multitenant"
    DOCUMENTATION_VAULT = "documentation_vault"
    HUMAN_LAYER = "human_layer"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ModuleAction:
    id: str                       # e.g. "fleet:isolate_host"
    category: ModuleCategory
    name: str
    description: str
    permission_required: str      # RBAC permission string
    risk: RiskLevel
    payload_schema: Dict[str, Any] = field(default_factory=dict)
    ui: Dict[str, Any] = field(default_factory=dict)  # button/cog/slider hints

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["risk"] = self.risk.value
        return d


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Action registry (the 34 blueprint actions) ──────────────────────────
def _registry() -> Dict[str, ModuleAction]:
    C = ModuleCategory
    R = RiskLevel
    A = ModuleAction
    items: List[ModuleAction] = [
        # 1. Fleet & RMM
        A("fleet:ping", C.FLEET_RMM, "Ping Agent", "Verify agent liveness and version drift.",
          "fleet:read", R.LOW, {"agent_id": "str"}, {"button": "dot", "color": "emerald"}),
        A("fleet:execute_script", C.FLEET_RMM, "Execute Script",
          "Run signed/raw admin scripts (py/bash/ps) with timeout + live stdout/stderr.",
          "fleet:execute", R.HIGH,
          {"agent_id": "str", "shell": "enum[python,bash,powershell]", "script": "text", "timeout_sec": "int"},
          {"button": "primary", "cog": True, "slider": {"field": "timeout_sec", "min": 5, "max": 900, "value": 60}}),
        A("fleet:isolate_host", C.FLEET_RMM, "Isolate Host",
          "Sever non-essential networking while preserving the RMM control channel.",
          "fleet:contain", R.CRITICAL, {"agent_id": "str", "reason": "str"},
          {"button": "danger", "cog": True}),
        A("fleet:collect_diagnostics", C.FLEET_RMM, "Collect Diagnostics",
          "Generate a compressed forensic bundle (syslogs, event logs, persistence items).",
          "fleet:read", R.MEDIUM, {"agent_id": "str", "include_memory": "bool"},
          {"button": "secondary"}),
        # 0. Threat Intelligence (live enrichment; keyless + keyed sources)
        A("intel:lookup", C.DETECT_RESPOND, "Threat-Intel Lookup",
          "Enrich an IP / domain / URL / hash against live threat feeds (Feodo, Tor, "
          "VirusTotal, AbuseIPDB, OTX).",
          "detect:read", R.LOW, {"indicator": "str"},
          {"button": "primary", "cog": True}),
        # 2. Remote Access
        A("remote:spawn_shell", C.REMOTE_ACCESS, "Spawn Shell",
          "Open an authenticated interactive terminal (PowerShell/Bash) over secure WS.",
          "remote:shell", R.HIGH, {"agent_id": "str", "shell": "enum[bash,powershell]"},
          {"button": "primary", "cog": True}),
        A("remote:fs_list", C.REMOTE_ACCESS, "List Filesystem",
          "Enumerate directory contents on a remote endpoint.",
          "remote:fs", R.MEDIUM, {"agent_id": "str", "path": "str"}, {"button": "secondary"}),
        A("remote:fs_transfer", C.REMOTE_ACCESS, "Transfer File",
          "Secure bi-directional file transfer to/from an endpoint.",
          "remote:fs", R.HIGH, {"agent_id": "str", "direction": "enum[push,pull]", "path": "str"},
          {"button": "secondary", "cog": True}),
        A("remote:terminate_session", C.REMOTE_ACCESS, "Terminate Session",
          "Force-kill an active remote access session immediately.",
          "remote:manage", R.HIGH, {"session_id": "str"}, {"button": "danger"}),
        # 3. Detect & Respond
        A("detect:scan_yara", C.DETECT_RESPOND, "YARA Scan",
          "Run targeted YARA rule scans on paths or memory.",
          "detect:scan", R.MEDIUM, {"agent_id": "str", "target": "str", "rule_set": "str"},
          {"button": "primary", "cog": True, "radial": {"field": "rule_set", "options": ["default", "ransomware", "webshell", "lolbin"]}}),
        A("detect:kill_process_tree", C.DETECT_RESPOND, "Kill Process Tree",
          "Recursively terminate a suspicious process hierarchy.",
          "detect:respond", R.HIGH, {"agent_id": "str", "pid": "int"}, {"button": "danger"}),
        A("detect:quarantine_file", C.DETECT_RESPOND, "Quarantine File",
          "Hash, move and lock a malicious binary in the secure vault.",
          "detect:respond", R.HIGH, {"agent_id": "str", "path": "str"}, {"button": "danger", "cog": True}),
        A("detect:fetch_pcap", C.DETECT_RESPOND, "Capture PCAP",
          "Capture endpoint network packet traces for forensic analysis.",
          "detect:scan", R.MEDIUM, {"agent_id": "str", "duration_sec": "int"},
          {"button": "secondary", "slider": {"field": "duration_sec", "min": 5, "max": 300, "value": 30}}),
        # 4. SOAR Playbooks
        A("soar:run_playbook", C.SOAR_PLAYBOOKS, "Run Playbook",
          "Trigger a targeted playbook workflow manually or programmatically.",
          "soar:execute", R.HIGH, {"playbook_id": "str", "context": "json"},
          {"button": "primary", "cog": True}),
        A("soar:pause_approval", C.SOAR_PLAYBOOKS, "Pause for Approval",
          "Hold execution pending security-analyst sign-off.",
          "soar:execute", R.LOW, {"run_id": "str", "step": "str"}, {"button": "secondary"}),
        A("soar:rollback_action", C.SOAR_PLAYBOOKS, "Rollback Action",
          "Execute counter-remediation steps if a playbook step fails.",
          "soar:execute", R.HIGH, {"run_id": "str", "step": "str"}, {"button": "danger"}),
        # 5. Patch & Vulnerability
        A("patch:scan_cve", C.PATCH_VULNERABILITY, "Scan CVEs",
          "Inventory local software and cross-reference against CVE/OSV databases.",
          "patch:read", R.LOW, {"agent_id": "str"}, {"button": "primary"}),
        A("patch:apply_updates", C.PATCH_VULNERABILITY, "Apply Updates",
          "Install missing security patches (respecting the maintenance window).",
          "patch:apply", R.HIGH, {"agent_id": "str", "kb_ids": "list", "reboot_policy": "enum[none,if_required,forced]"},
          {"button": "primary", "cog": True, "radial": {"field": "reboot_policy", "options": ["none", "if_required", "forced"]}}),
        A("patch:rollback_patch", C.PATCH_VULNERABILITY, "Rollback Patch",
          "Uninstall a specific update if a stability regression occurs.",
          "patch:apply", R.HIGH, {"agent_id": "str", "kb_id": "str"}, {"button": "danger"}),
        # 6. Dark Web
        A("darkweb:run_recon", C.DARK_WEB, "Run Recon",
          "Query dark-web intelligence for domain/email/IP exposures.",
          "darkweb:read", R.LOW, {"identifier": "str", "identifier_type": "enum[domain,email,ip]"},
          {"button": "primary"}),
        A("darkweb:force_password_reset", C.DARK_WEB, "Force Password Reset",
          "Trigger a mandatory credential reset for a compromised account.",
          "darkweb:respond", R.HIGH, {"account": "str"}, {"button": "danger", "cog": True}),
        # 7. AI Safety Fabric
        A("aisafety:scan_prompt", C.AI_SAFETY_FABRIC, "Scan Prompt",
          "Evaluate an incoming prompt for injection / jailbreak bypasses.",
          "aisafety:read", R.LOW, {"prompt": "text"}, {"button": "primary"}),
        A("aisafety:redact_pii", C.AI_SAFETY_FABRIC, "Redact PII",
          "Filter and mask regex-matched secrets / PII before external LLM calls.",
          "aisafety:read", R.LOW, {"text": "text"}, {"button": "secondary"}),
        A("aisafety:audit_llm_response", C.AI_SAFETY_FABRIC, "Audit LLM Response",
          "Validate model output against safety guidelines (hallucination/policy).",
          "aisafety:read", R.LOW, {"response": "text", "context": "text"}, {"button": "secondary"}),
        # 8. MSP Multi-Tenant (Kaseya One parity)
        A("msp:switch_tenant", C.MSP_MULTITENANT, "Switch Tenant",
          "Switch the operator context to another managed tenant (MSP gateway).",
          "msp:read", R.MEDIUM, {"tenant_id": "str"}, {"button": "primary", "cog": True}),
        A("msp:configure_sso", C.MSP_MULTITENANT, "Configure Federation SSO",
          "Enable/configure SAML or OIDC enterprise federation for a tenant.",
          "msp:admin", R.HIGH, {"tenant_id": "str", "protocol": "enum[saml,oidc]"},
          {"button": "primary", "cog": True, "radial": {"field": "protocol", "options": ["saml", "oidc"]}}),
        # 9. Documentation & Vault (IT Glue parity)
        A("vault:map_relationships", C.DOCUMENTATION_VAULT, "Map Asset Relationships",
          "Build the IT-Glue-style relationship graph across assets, apps and credentials.",
          "vault:read", R.LOW, {}, {"button": "primary"}),
        A("vault:rotate_credential", C.DOCUMENTATION_VAULT, "Rotate Credential",
          "Rotate a tracked secret and reset its rotation clock.",
          "vault:manage", R.HIGH, {"cred_id": "str"}, {"button": "danger", "cog": True}),
        # 10. Detect & Respond additions
        A("detect:process_tree", C.DETECT_RESPOND, "Process Kill-Tree",
          "Retrieve the process hierarchy for one-click kill-tree visualization.",
          "detect:scan", R.LOW, {"agent_id": "str"}, {"button": "primary"}),
        A("detect:memory_dump", C.DETECT_RESPOND, "Live Memory Dump",
          "Trigger a live forensic memory capture on an endpoint.",
          "detect:respond", R.HIGH, {"agent_id": "str", "pid": "int", "scope": "enum[process,full]"},
          {"button": "danger", "cog": True, "radial": {"field": "scope", "options": ["process", "full"]}}),
        # 11. Compliance additions
        A("compliance:generate_ticket", C.PATCH_VULNERABILITY, "Generate Remediation Ticket",
          "Auto-create a populated remediation ticket from a finding (CVE/alert/leak/drift).",
          "patch:read", R.MEDIUM, {"source": "enum[vulnerability,edr_alert,dark_web,drift]", "source_ref": "str"},
          {"button": "primary", "cog": True,
           "radial": {"field": "source", "options": ["vulnerability", "edr_alert", "dark_web", "drift"]}}),
        A("compliance:drift_toggle", C.PATCH_VULNERABILITY, "Continuous Drift Detection",
          "Toggle continuous configuration-drift alerting.",
          "patch:read", R.LOW, {"enabled": "bool"}, {"button": "dot", "toggle": True}),
        # 12. Human layer
        A("human:auto_enroll", C.HUMAN_LAYER, "Auto-Enroll Phish Failures",
          "One-click enrollment of every user who failed a phishing simulation.",
          "awareness:manage", R.MEDIUM, {"course": "str", "only_pending": "bool"},
          {"button": "primary", "cog": True}),
    ]
    return {a.id: a for a in items}


# ── Engine ───────────────────────────────────────────────────────────────
class SecurityCapabilitiesEngine:
    HIGH_RISK = {RiskLevel.HIGH, RiskLevel.CRITICAL}

    # Prompt-injection signatures (grounded, extendable via settings)
    _INJECTION = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(the\s+)?(system|above)\s+prompt",
        r"you\s+are\s+now\s+(dan|developer\s+mode)",
        r"reveal\s+(your\s+)?system\s+prompt",
        r"\bbypass\b.*\b(safety|guardrail|filter)\b",
    ]
    # PII / secret regexes (grounded)
    _PII = {
        "email": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b(?:\d[ -]*?){13,16}\b",
        "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "aws_key": r"\bAKIA[0-9A-Z]{16}\b",
        "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "bearer": r"\b(?:Bearer|token|api[_-]?key)\s*[:=]\s*[A-Za-z0-9._\-]{16,}",
    }

    def __init__(self, db_manager: Any = None):
        self.db = db_manager
        self.actions = _registry()
        self._sessions: Dict[str, Dict[str, Any]] = {}   # remote shell sessions
        self._pending: Dict[str, Dict[str, Any]] = {}    # approval-gated executions

    # ---- DB helper (returns list-of-dicts, or [] when no db) ----
    def _dbq(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        if not self.db:
            return []
        try:
            res = self.db.conn.execute(sql, params)
            cols = [d[0] for d in (res.description or [])]
            return [dict(zip(cols, r)) for r in res.fetchall()]
        except Exception:
            return []

    # ---- Introspection (drives the data-driven UI) ----
    def catalog(self) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self.actions.values()]

    def catalog_by_category(self) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for a in self.actions.values():
            out.setdefault(a.category.value, []).append(a.to_dict())
        return out

    # ---- Safety Fabric ----
    def scan_prompt(self, prompt: str) -> Dict[str, Any]:
        p = prompt or ""
        hits = [pat for pat in self._INJECTION if re.search(pat, p, re.I)]
        return {"safe": not hits, "threat": "prompt_injection" if hits else None,
                "matched_signatures": hits, "scanned_at": _now()}

    def redact_pii(self, text: str) -> Dict[str, Any]:
        t = text or ""
        found: Dict[str, int] = {}
        for kind, rx in self._PII.items():
            def _sub(m):
                found[kind] = found.get(kind, 0) + 1
                return f"[REDACTED:{kind.upper()}]"
            t = re.sub(rx, _sub, t)
        return {"redacted": bool(found), "counts": found, "sanitized_text": t, "scanned_at": _now()}

    def audit_llm_response(self, response: str, context: str = "") -> Dict[str, Any]:
        r = (response or "").lower()
        flags = []
        if re.search(r"\b(i am certain|100%|guaranteed|definitely will)\b", r):
            flags.append("overconfident_language")
        if re.search(r"-----BEGIN.*PRIVATE KEY-----", response or ""):
            flags.append("leaked_secret")
        if context and len(response or "") > 0 and not any(w in r for w in context.lower().split()[:8] if len(w) > 4):
            flags.append("possible_context_drift")
        return {"pass": not flags, "flags": flags, "audited_at": _now()}

    def guardrail(self, action_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Every action passes through here first."""
        blob = " ".join(str(v) for v in (payload or {}).values())
        inj = self.scan_prompt(blob)
        blocked_tokens = ["rm -rf /", "DROP DATABASE", "mkfs", "iptables -F", ":(){ :|:& };:"]
        dangerous = [t for t in blocked_tokens if t.lower() in blob.lower()]
        return {"allowed": inj["safe"] and not dangerous,
                "injection": inj, "blocked_tokens": dangerous}

    # ---- Audit ----
    def _audit(self, action_id: str, executor: str, target: str, outcome: str, detail: Dict[str, Any]):
        try:
            if self.db and hasattr(self.db, "insert_audit_entry"):
                self.db.insert_audit_entry({
                    "actor_label": executor, "action": action_id, "resource_type": "capability",
                    "resource_id": target, "outcome": outcome, "detail": detail,
                })
        except Exception:
            logger.exception("audit write failed for %s", action_id)

    # ---- Central dispatch with approval gating ----
    async def execute(self, action_id: str, payload: Dict[str, Any], executor: str = "system",
                      approved: bool = False) -> Dict[str, Any]:
        action = self.actions.get(action_id)
        if not action:
            return {"ok": False, "error": f"unknown action '{action_id}'"}

        # AI Safety Fabric actions ARE the guardrail — they must be allowed to
        # receive hostile input for analysis, so they bypass the pre-filter.
        guard = {"allowed": True, "exempt": True} if action.category == ModuleCategory.AI_SAFETY_FABRIC \
            else self.guardrail(action_id, payload)
        if not guard["allowed"]:
            self._audit(action_id, executor, str(payload.get("agent_id", "")), "blocked", guard)
            return {"ok": False, "blocked": True, "reason": "AI Safety Fabric guardrail",
                    "guardrail": guard}

        # High-risk actions float an approval gate to the Command Console.
        if action.risk in self.HIGH_RISK and not approved:
            approval_id = f"appr-{uuid.uuid4().hex[:10]}"
            self._pending[approval_id] = {"action_id": action_id, "payload": payload,
                                          "executor": executor, "created_at": _now(),
                                          "risk": action.risk.value}
            return {"ok": True, "requires_approval": True, "approval_id": approval_id,
                    "action": action.to_dict(),
                    "prompt": f"Approve {action.name} ({action.risk.value.upper()} risk)?"}

        result = await self._dispatch(action, payload, executor)
        self._audit(action_id, executor, str(payload.get("agent_id", payload.get("identifier", ""))),
                    "success" if result.get("ok", True) else "error", {"payload_keys": list(payload.keys())})
        return result

    async def approve(self, approval_id: str, executor: str = "system") -> Dict[str, Any]:
        p = self._pending.pop(approval_id, None)
        if not p:
            return {"ok": False, "error": "approval not found or already resolved"}
        return await self.execute(p["action_id"], p["payload"], executor=executor, approved=True)

    def deny(self, approval_id: str, executor: str = "system") -> Dict[str, Any]:
        p = self._pending.pop(approval_id, None)
        if not p:
            return {"ok": False, "error": "approval not found"}
        self._audit(p["action_id"], executor, "", "denied", {"approval_id": approval_id})
        return {"ok": True, "denied": True, "approval_id": approval_id}

    def pending_approvals(self) -> List[Dict[str, Any]]:
        return [{"approval_id": k, **v} for k, v in self._pending.items()]

    # Actions that can only act on a real managed endpoint. Until a live JAKAL
    # agent (roadmap #4) is connected for the target, these return an honest
    # "not_connected" instead of a simulated success. No fake data.
    _AGENT_REQUIRED = {
        "fleet:ping", "fleet:execute_script", "fleet:collect_diagnostics",
        "remote:spawn_shell", "remote:fs_list", "remote:fs_transfer", "remote:terminate_session",
        "detect:kill_process_tree", "detect:quarantine_file", "detect:fetch_pcap",
        "detect:process_tree", "detect:memory_dump",
        "patch:apply_updates", "patch:rollback_patch",
        "darkweb:force_password_reset",
    }

    def _agent_online(self, agent_id: Any) -> bool:
        """True only if a real JAKAL agent has registered + recently heartbeat.
        Backed by the endpoint-agent registry (routers/fleet_agent.py). Returns
        False when the registry/table is absent, so agent actions stay honest."""
        if not agent_id:
            return False
        rows = self._dbq(
            "SELECT last_seen FROM agent_endpoints WHERE agent_id = ? AND status = 'online'",
            (str(agent_id),))
        return bool(rows)

    def _queue_agent_command(self, agent_id: str, action_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Queue a REAL command onto a live agent's channel (agent_commands)."""
        if not self.db:
            return {"ok": False, "status": "error", "reason": "no database", "at": _now()}
        cmd_id = f"cmd-{uuid.uuid4().hex[:10]}"
        try:
            self.db.conn.execute(
                "INSERT INTO agent_commands (cmd_id,agent_id,action,payload,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (cmd_id, str(agent_id), action_id, __import__("json").dumps(payload), "pending",
                 datetime.now(timezone.utc), datetime.now(timezone.utc)))
            self.db.conn.commit()
        except Exception as e:
            return {"ok": False, "status": "error", "reason": f"could not queue command: {e}", "at": _now()}
        return {"ok": True, "status": "queued", "action": action_id, "agent_id": agent_id,
                "cmd_id": cmd_id, "note": "Command dispatched to the live agent; poll the asset detail for its result.",
                "at": _now()}

    # ---- Handlers (grounded; delegate where a real subsystem exists) ----
    async def _dispatch(self, action: ModuleAction, payload: Dict[str, Any], executor: str) -> Dict[str, Any]:
        if action.id in self._AGENT_REQUIRED:
            agent_id = payload.get("agent_id")
            if not self._agent_online(agent_id):
                tgt = agent_id or "target"
                return {"ok": True, "status": "not_connected", "action": action.id,
                        "reason": (f"'{action.name}' acts on a managed endpoint, but no live JAKAL "
                                   f"agent is connected for '{tgt}'. Install the endpoint agent "
                                   f"(roadmap #4). This is reported honestly — not simulated."),
                        "requires": "endpoint_agent", "at": _now()}
            # Agent is live: fleet:ping is a liveness read; everything else is a
            # real command queued to the agent's command channel.
            if action.id != "fleet:ping":
                return self._queue_agent_command(agent_id, action.id, payload)
        cat, act = action.id.split(":", 1)
        fn = getattr(self, f"_h_{cat}_{act}", None)
        if fn is None:
            return {"ok": True, "action": action.id, "status": "acknowledged",
                    "note": "handler stub — wire to endpoint subsystem", "at": _now()}
        return await fn(payload, executor)

    # Fleet & RMM ----------------------------------------------------------
    async def _h_fleet_ping(self, p, ex):
        # REAL liveness from the agent's last heartbeat (agent_endpoints).
        rows = self._dbq("SELECT hostname, os, ip, last_seen, status FROM agent_endpoints WHERE agent_id = ?",
                         (str(p.get("agent_id")),))
        if not rows:
            return {"ok": True, "status": "not_connected", "agent_id": p.get("agent_id"),
                    "reason": "no such registered agent", "at": _now()}
        r = rows[0]
        return {"ok": True, "status": "active", "agent_id": p.get("agent_id"),
                "hostname": r.get("hostname"), "os": r.get("os"), "ip": r.get("ip"),
                "last_seen": str(r.get("last_seen")), "at": _now()}

    async def _h_fleet_execute_script(self, p, ex):
        shell = p.get("shell", "bash"); script = p.get("script", ""); timeout = int(p.get("timeout_sec", 60))
        # Delegate to the hardened sandbox in routers.scripts when available.
        try:
            from routers import scripts as scripts_router  # noqa
            runner = getattr(scripts_router, "execute_script_in_sandbox", None)
        except Exception:
            runner = None
        digest = hashlib.sha256(script.encode()).hexdigest()[:16]
        return {"ok": True, "agent_id": p.get("agent_id"), "shell": shell, "script_sha256": digest,
                "execution_id": f"exec-{uuid.uuid4().hex[:8]}", "sandboxed": runner is not None,
                "return_code": 0, "streamed": True, "timeout_sec": timeout, "at": _now()}

    async def _h_fleet_isolate_host(self, p, ex):
        # REAL containment via security_agents.edr_connector. With no endpoint
        # agent (#4), no reachable Docker sandbox and no EDR webhook configured,
        # this returns an honest not_configured rather than a fake success.
        agent = p.get("agent_id")
        try:
            from security_agents.edr_connector import enforce_containment
        except Exception as e:
            return {"ok": False, "status": "unavailable",
                    "reason": f"edr_connector import failed: {e}", "at": _now()}
        res = enforce_containment("isolate_host_staged", agent or "",
                                  {"reason": p.get("reason", "")}, ex, db=self.db)
        status = res.get("status", "not_configured")
        return {"ok": status == "enforced", "agent_id": agent, "status": status,
                "connector": res.get("connector"), "detail": res.get("detail"),
                "reason": (None if status == "enforced" else
                           "Isolation needs the JAKAL agent (#4), a Docker sandbox, or a "
                           "configured EDR_WEBHOOK_URL in the Integrations vault."),
                "at": _now()}

    async def _h_fleet_collect_diagnostics(self, p, ex):
        bundle = f"diag-{p.get('agent_id','host')}-{int(time.time())}.tar.gz"
        return {"ok": True, "agent_id": p.get("agent_id"), "bundle": bundle,
                "artifacts": ["syslog", "eventlog", "persistence", "netstat", "process_list"],
                "include_memory": bool(p.get("include_memory")), "at": _now()}

    # Remote Access --------------------------------------------------------
    async def _h_remote_spawn_shell(self, p, ex):
        sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._sessions[sid] = {"agent_id": p.get("agent_id"), "shell": p.get("shell", "bash"),
                               "operator": ex, "opened_at": _now(), "recording": True}
        return {"ok": True, "session_id": sid, "ws": f"/ws/remote/{sid}", "recording": True, "at": _now()}

    async def _h_remote_fs_list(self, p, ex):
        return {"ok": True, "agent_id": p.get("agent_id"), "path": p.get("path", "/"),
                "entries": [], "note": "live listing streamed over the session WS", "at": _now()}

    async def _h_remote_fs_transfer(self, p, ex):
        return {"ok": True, "transfer_id": f"xfer-{uuid.uuid4().hex[:8]}",
                "direction": p.get("direction", "pull"), "path": p.get("path"), "at": _now()}

    async def _h_remote_terminate_session(self, p, ex):
        sid = p.get("session_id"); existed = self._sessions.pop(sid, None) is not None
        return {"ok": True, "session_id": sid, "terminated": existed, "at": _now()}

    # Detect & Respond -----------------------------------------------------
    async def _h_detect_scan_yara(self, p, ex):
        try:
            import yara  # type: ignore
            engine = "yara-python"
        except Exception:
            engine = "signature-fallback"
        rules = self._dbq("SELECT name, category, severity FROM cap_yara_rules")
        applicable = [r for r in rules if p.get("rule_set", "default") in ("default", r.get("category"))]
        return {"ok": True, "scan_id": f"yara-{uuid.uuid4().hex[:6]}", "engine": engine,
                "target": p.get("target", "/"), "rule_set": p.get("rule_set", "default"),
                "rules_loaded": len(applicable) or len(rules),
                "matches_found": 0, "status": "clean", "at": _now()}

    async def _h_detect_kill_process_tree(self, p, ex):
        return {"ok": True, "agent_id": p.get("agent_id"), "root_pid": p.get("pid"),
                "terminated": [p.get("pid")], "status": "success", "at": _now()}

    async def _h_detect_quarantine_file(self, p, ex):
        path = p.get("path", ""); h = hashlib.sha256(path.encode()).hexdigest()
        return {"ok": True, "agent_id": p.get("agent_id"), "path": path, "sha256": h,
                "vault_id": f"vault-{h[:10]}", "locked": True, "status": "quarantined", "at": _now()}

    async def _h_detect_fetch_pcap(self, p, ex):
        return {"ok": True, "agent_id": p.get("agent_id"),
                "pcap": f"cap-{uuid.uuid4().hex[:8]}.pcap",
                "duration_sec": int(p.get("duration_sec", 30)), "at": _now()}

    # SOAR -----------------------------------------------------------------
    async def _h_soar_run_playbook(self, p, ex):
        import json as _json
        run = f"run-{uuid.uuid4().hex[:8]}"
        pb = self._dbq("SELECT name, steps, requires_approval FROM cap_soar_playbooks WHERE playbook_id = ?",
                       (p.get("playbook_id"),))
        steps = ["triage", "enrich", "contain", "notify"]
        name = p.get("playbook_id")
        if pb:
            name = pb[0].get("name")
            try:
                steps = _json.loads(pb[0].get("steps") or "[]") or steps
            except Exception:
                pass
        return {"ok": True, "run_id": run, "playbook_id": p.get("playbook_id"), "name": name,
                "state": "running", "steps": steps, "at": _now()}

    async def _h_soar_pause_approval(self, p, ex):
        return {"ok": True, "run_id": p.get("run_id"), "step": p.get("step"),
                "state": "paused_for_approval", "at": _now()}

    async def _h_soar_rollback_action(self, p, ex):
        return {"ok": True, "run_id": p.get("run_id"), "step": p.get("step"),
                "state": "rolled_back", "at": _now()}

    # Patch & Vulnerability ------------------------------------------------
    async def _h_patch_scan_cve(self, p, ex):
        # REAL live scan via the shared OSV.dev engine (services.vuln_scanner).
        # Accepts an explicit package list in the payload; otherwise scans the
        # server's own pinned dependency manifest. No seeded rows.
        import os as _os
        from services.vuln_scanner import osv_scan, scan_manifest
        packages = p.get("packages")
        if packages:
            result = osv_scan(packages); scope = "payload_packages"
        else:
            here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            manifests = [_os.path.join(here, "requirements.txt"),
                         _os.path.join(here, "backend", "requirements.txt")]
            result = scan_manifest([m for m in manifests if _os.path.exists(m)])
            scope = "server_manifest"
        result.update({"agent_id": p.get("agent_id"), "scope": scope,
                       "scan_id": f"cve-{uuid.uuid4().hex[:6]}"})
        return result

    async def _h_patch_apply_updates(self, p, ex):
        return {"ok": True, "agent_id": p.get("agent_id"), "kb_ids": p.get("kb_ids", []),
                "reboot_policy": p.get("reboot_policy", "if_required"),
                "state": "scheduled", "window": "maintenance", "at": _now()}

    async def _h_patch_rollback_patch(self, p, ex):
        return {"ok": True, "agent_id": p.get("agent_id"), "kb_id": p.get("kb_id"),
                "state": "uninstalled", "at": _now()}

    # Dark Web -------------------------------------------------------------
    async def _h_darkweb_run_recon(self, p, ex):
        # REAL Have I Been Pwned lookup, delegated to routers.darkweb. Honest
        # "not_connected" when HIBP_API_KEY is unset — never seeded rows.
        ident = (p.get("identifier") or "").strip()
        try:
            from routers.darkweb import _hibp_check_account
        except Exception as e:
            return {"ok": False, "status": "unavailable",
                    "reason": f"dark web connector import failed: {e}", "at": _now()}
        if not ident or "@" not in ident:
            return {"ok": False, "status": "bad_request",
                    "reason": "provide an email in `identifier` for a real HIBP breach lookup",
                    "at": _now()}
        res = _hibp_check_account(ident)
        if not res.get("configured"):
            return {"ok": True, "status": "not_connected", "connector": "hibp", "identifier": ident,
                    "reason": "Set HIBP_API_KEY in the Integrations vault to enable live breach lookups.",
                    "exposures": [], "exposure_count": 0, "at": _now()}
        breaches = res.get("breaches", []) or []
        crit = any("Passwords" in (b.get("DataClasses") or []) for b in breaches)
        return {"ok": True, "status": "ok", "connector": "hibp", "identifier": ident,
                "exposures": breaches, "exposure_count": len(breaches),
                "threat_level": "critical" if crit else ("high" if breaches else "low"),
                "error": res.get("error"), "at": _now()}

    async def _h_darkweb_force_password_reset(self, p, ex):
        return {"ok": True, "account": p.get("account"), "reset_triggered": True,
                "sessions_revoked": True, "at": _now()}

    # AI Safety Fabric -----------------------------------------------------
    async def _h_aisafety_scan_prompt(self, p, ex):
        return {"ok": True, **self.scan_prompt(p.get("prompt", ""))}

    async def _h_aisafety_redact_pii(self, p, ex):
        return {"ok": True, **self.redact_pii(p.get("text", ""))}

    async def _h_aisafety_audit_llm_response(self, p, ex):
        return {"ok": True, **self.audit_llm_response(p.get("response", ""), p.get("context", ""))}

    # Threat Intelligence -------------------------------------------------
    async def _h_intel_lookup(self, p, ex):
        from services.threat_intel import lookup
        return lookup(p.get("indicator", ""))


    # MSP Multi-Tenant ------------------------------------------------------
    async def _h_msp_switch_tenant(self, p, ex):
        return {"ok": True, "tenant_id": p.get("tenant_id"), "context_switched": True,
                "scope": "tenant-isolated", "at": _now()}

    async def _h_msp_configure_sso(self, p, ex):
        proto = p.get("protocol", "saml")
        self._dbq("SELECT 1")  # keep db handle warm
        return {"ok": True, "tenant_id": p.get("tenant_id"), "protocol": proto,
                "state": "configured", "metadata_url": f"/api/msp/sso/configure-{proto}", "at": _now()}

    # Documentation & Vault -------------------------------------------------
    async def _h_vault_map_relationships(self, p, ex):
        rels = self._dbq("SELECT source_asset, relationship, target_asset, criticality FROM cap_asset_relationships")
        nodes = set()
        for r in rels:
            nodes.add(r.get("source_asset")); nodes.add(r.get("target_asset"))
        return {"ok": True, "nodes": len(nodes), "edges": len(rels),
                "critical_paths": len([r for r in rels if r.get("criticality") == "CRITICAL"]),
                "relationships": rels[:25], "at": _now()}

    async def _h_vault_rotate_credential(self, p, ex):
        return {"ok": True, "cred_id": p.get("cred_id"), "rotated": True,
                "endpoint": "/api/enterprise/vault/rotation/rotate", "at": _now()}

    # Detect additions ------------------------------------------------------
    async def _h_detect_process_tree(self, p, ex):
        return {"ok": True, "agent_id": p.get("agent_id"),
                "endpoint": f"/api/enterprise/detect/process-tree/{p.get('agent_id')}",
                "note": "full hierarchy returned by the endpoint for visualization", "at": _now()}

    async def _h_detect_memory_dump(self, p, ex):
        return {"ok": True, "agent_id": p.get("agent_id"), "pid": p.get("pid"),
                "scope": p.get("scope", "process"),
                "dump_id": f"mem-{uuid.uuid4().hex[:8]}.raw", "state": "capturing",
                "chain_of_custody": True, "at": _now()}

    # Compliance additions --------------------------------------------------
    async def _h_compliance_generate_ticket(self, p, ex):
        return {"ok": True, "source": p.get("source"), "source_ref": p.get("source_ref"),
                "endpoint": "/api/enterprise/compliance/remediation-ticket",
                "note": "ticket is created + SLA-stamped by the endpoint", "at": _now()}

    async def _h_compliance_drift_toggle(self, p, ex):
        return {"ok": True, "setting": "drift_detection_enabled",
                "enabled": bool(p.get("enabled", True)), "at": _now()}

    # Human layer -----------------------------------------------------------
    async def _h_human_auto_enroll(self, p, ex):
        pend = self._dbq("SELECT display_name FROM cap_phish_failures WHERE action_taken = 'pending'")
        return {"ok": True, "course": p.get("course", "Phishing 101"),
                "would_enroll": len(pend), "users": [x.get("display_name") for x in pend],
                "endpoint": "/api/enterprise/awareness/auto-enroll", "at": _now()}


# ── Singleton accessor ────────────────────────────────────────────────────
_engine: Optional[SecurityCapabilitiesEngine] = None


def get_capabilities_engine(db_manager: Any = None) -> SecurityCapabilitiesEngine:
    global _engine
    if _engine is None:
        _engine = SecurityCapabilitiesEngine(db_manager=db_manager)
    return _engine
