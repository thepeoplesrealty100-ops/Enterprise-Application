"""
backend/payloads/script_catalog.py
=====================================
Indexes the real, runnable scripts already sitting in gacyber_toolkit/'s
phase folders (01-Reconnaissance through 07-Post-Exploitation) — .py, .sh,
.pl, .rb files that were on disk but had no API surface, no risk
classification, and no path into the platform's execution machinery.

This does NOT introduce a new execution model. It follows the same
philosophy already established by security_agents/exploit_agent.py
("produces structured, reviewed command sets rather than auto-running
them against a target") and wrappers/base.py (argv-list subprocess, no
shell=True, target allowlist via sanitize_target): a catalog entry can be
QUEUED for execution, which stages it behind the authorization gate +
Human Approval Gate exactly like a payload, and — once approved — is
run only inside a sandbox container the operator already provisioned via
VMOrchestrator (backend/security_agents/vm_orchestrator.py), never as a
direct host subprocess against an arbitrary target. See routers/response.py.

Risk classification is a static heuristic based on directory + filename
keywords (bruteforce/exploit/persistence/privilege-escalation score
higher than passive recon/DNS lookups) — deliberately explainable, same
principle as threat_scoring.py's keyword tables.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCRIPT_EXTENSIONS = {".py": "python", ".sh": "bash", ".pl": "perl", ".rb": "ruby"}

# Directory name -> (phase key used elsewhere in this app, human label)
_PHASE_DIR_MAP: Dict[str, tuple] = {
    "01-Reconnaissance": ("recon_passive", "Reconnaissance"),
    "02-Scanning": ("recon_active", "Scanning"),
    "03-Enumeration": ("enumeration", "Enumeration"),
    "04-Web-Application": ("web_application", "Web Application"),
    "05-Wireless": ("wireless", "Wireless"),
    "06-Exploitation": ("exploitation", "Exploitation"),
    "07-Post-Exploitation": ("post_exploitation_assessment", "Post-Exploitation"),
    "08-Reporting": ("reporting", "Reporting"),
}

# Keyword -> risk level. Highest match wins. Matched against the relative
# path (folder + filename) in lowercase.
_RISK_KEYWORDS: List[tuple] = [
    ("privilege_escalate", "HIGH"), ("privesc", "HIGH"), ("persistence", "HIGH"),
    ("gainaccess", "HIGH"), ("exploit", "HIGH"),
    ("bruteforce", "MEDIUM"), ("fuzz", "MEDIUM"), ("injection", "MEDIUM"),
    ("vulnerability", "MEDIUM"), ("scan", "MEDIUM"), ("crlf", "MEDIUM"),
    ("post-exploitation", "MEDIUM"),
    ("enumerate", "LOW"), ("footprint", "LOW"), ("mirror", "LOW"),
    ("banner", "LOW"), ("whois", "LOW"), ("dns", "LOW"), ("osint", "LOW"),
    ("header_analysis", "LOW"),
]
_DEFAULT_RISK = "LOW"


def _classify_risk(rel_path: str) -> str:
    lowered = rel_path.lower()
    for keyword, risk in _RISK_KEYWORDS:
        if keyword in lowered:
            return risk
    return _DEFAULT_RISK


def _extract_description(content: str, language: str) -> str:
    """Pull the first meaningful comment line as a human description."""
    comment_prefix = "#"
    for raw_line in content.splitlines()[:20]:
        line = raw_line.strip()
        if not line or line in ("#!/bin/bash", "#!/usr/bin/env python3", "#!/usr/bin/perl", "#!/usr/bin/env ruby"):
            continue
        if line.startswith(comment_prefix):
            candidate = line.lstrip("#").strip()
            if candidate and not candidate.lower().startswith(("coding:", "-*-")):
                return candidate
        elif not line.startswith(comment_prefix):
            # First non-comment, non-shebang line — stop looking further up.
            break
    return ""


def _find_toolkit_root() -> Optional[Path]:
    here = Path(__file__).resolve().parent  # backend/payloads
    candidates = [
        Path.cwd() / "gacyber_toolkit",
        here.parent / "gacyber_toolkit",       # backend/gacyber_toolkit (not expected, cheap check)
        here.parent.parent / "gacyber_toolkit",  # repo_root/gacyber_toolkit (expected)
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


class ScriptCatalog:
    """Loads and classifies every runnable script under gacyber_toolkit/'s phase folders."""

    def __init__(self, toolkit_root: Optional[str] = None):
        self.toolkit_root = Path(toolkit_root) if toolkit_root else _find_toolkit_root()
        self._entries: Dict[str, Dict[str, Any]] = {}
        self.loaded = False
        self._load()

    def _load(self) -> None:
        if not self.toolkit_root or not self.toolkit_root.is_dir():
            logger.warning("gacyber_toolkit root not found — script catalog will be empty")
            return

        seen_by_name: Dict[str, str] = {}  # filename -> script_id, to dedupe the flat CheatSheets/ mirror
        for phase_dir, (phase_key, phase_label) in _PHASE_DIR_MAP.items():
            root = self.toolkit_root / phase_dir
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in _SCRIPT_EXTENSIONS:
                    continue
                if path.name in seen_by_name:
                    continue  # keep first (phase-folder) occurrence only
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    logger.warning("Could not read script %s: %s", path, e)
                    continue

                rel_path = str(path.relative_to(self.toolkit_root))
                language = _SCRIPT_EXTENSIONS[path.suffix.lower()]
                script_id = re.sub(r"[^a-z0-9_]+", "_", path.stem.lower()).strip("_")
                # Disambiguate id collisions across phases (rare, but Directory_Bruteforce
                # style names could theoretically repeat under a different phase folder).
                base_id = script_id
                n = 2
                while script_id in self._entries:
                    script_id = f"{base_id}_{n}"
                    n += 1

                entry = {
                    "id": script_id,
                    "title": path.stem.replace("_", " ").strip(),
                    "filename": path.name,
                    "phase": phase_key,
                    "phase_label": phase_label,
                    "language": language,
                    "risk_level": _classify_risk(rel_path),
                    "description": _extract_description(content, language) or f"{language} script from {phase_label}.",
                    "relative_path": rel_path,
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "line_count": content.count("\n") + 1,
                    "content": content,
                }
                self._entries[script_id] = entry
                seen_by_name[path.name] = script_id

        self.loaded = True
        logger.info(
            "ScriptCatalog loaded: %d scripts across %d phases from %s",
            len(self._entries), len({e["phase"] for e in self._entries.values()}), self.toolkit_root,
        )

    def list_scripts(self, phase: Optional[str] = None, risk_level: Optional[str] = None,
                      language: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for e in self._entries.values():
            if phase and e["phase"] != phase:
                continue
            if risk_level and e["risk_level"] != risk_level:
                continue
            if language and e["language"] != language:
                continue
            out.append({k: v for k, v in e.items() if k != "content"})
        return sorted(out, key=lambda e: (e["phase"], e["title"]))

    def get_script(self, script_id: str) -> Optional[Dict[str, Any]]:
        return self._entries.get(script_id)

    def stats(self) -> Dict[str, Any]:
        by_phase: Dict[str, int] = {}
        by_risk: Dict[str, int] = {}
        for e in self._entries.values():
            by_phase[e["phase"]] = by_phase.get(e["phase"], 0) + 1
            by_risk[e["risk_level"]] = by_risk.get(e["risk_level"], 0) + 1
        return {
            "total_scripts": len(self._entries),
            "by_phase": by_phase,
            "by_risk": by_risk,
            "toolkit_root": str(self.toolkit_root) if self.toolkit_root else None,
        }
