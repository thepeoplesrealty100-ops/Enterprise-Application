"""
backend/payloads/cheatsheet_ontology.py
=======================================
Ontology layer over the GACyber CheatSheet Library (gacyber_toolkit).

Design pattern — Palantir AIP Ontology:
  The Palantir Ontology models an operation as OBJECTS (nouns), LINKS
  (relationships), and ACTIONS/FUNCTIONS bound to a governed catalog, so an
  AI agent can only act through pre-authorized, audited operations rather than
  free-form command invention. (Ref: Palantir "AIP architecture" / "Ontology
  system" docs.)

This module turns the static cheatsheet library (cheatsheet_data.json — 13
report modules + 43 tool cheat sheets, plus the on-disk script tree) into a
queryable ontology:

  OBJECTS:  CheatsheetEntry (a tool or module), Phase, Category, Command
  LINKS:    Phase --contains--> Category --contains--> CheatsheetEntry
            CheatsheetEntry --exposes--> Command
  ACTIONS:  resolve(phase|category|keyword|tool_id) -> bounded entry set
            extract_commands(entry) -> parameterizable command templates

The AIP payload generator (aip_payload_generator.py) consumes this ontology so
that every generated payload is traceable to a real cheatsheet object — the
agent selects from the catalog, it does not fabricate tradecraft.

SAFETY BOUNDARY:
  Categories in _NON_EXECUTABLE_CATEGORIES (e.g. social engineering) are
  indexed as READ-ONLY reference documentation and are NEVER emitted as
  executable/generated payloads. This preserves the project rule against a
  generative phishing / social-engineering payload capability.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Categories that may be surfaced as reference text but never turned into
# generated, executable payloads.
_NON_EXECUTABLE_CATEGORIES = {"social-eng", "social_engineering", "phishing"}

# CPENT / PTES phase -> cheatsheet categories that belong to that phase.
# Categories come from cheatsheet_data.json ("category" field) and the
# on-disk phase folders (01-Reconnaissance ... 08-Reporting).
_PHASE_CATEGORY_MAP: Dict[str, List[str]] = {
    "recon_passive":               ["recon", "osint"],
    "recon_active":                ["recon", "scanning", "network"],
    "enumeration":                 ["enumeration", "network", "web-app"],
    "web_application":             ["web-app", "api"],
    "wireless":                    ["wireless"],
    "vulnerability_analysis":      ["scanning", "web-app", "exploitation"],
    "exploitation":                ["exploitation"],
    "post_exploitation_assessment":["post-exploit", "exploitation"],
    "lateral_movement":            ["post-exploit", "network"],
    "evasion":                     ["evasion"],
    "iot":                         ["iot"],
    "encryption_analysis":         ["network", "web-app"],
    "reporting":                   ["reporting"],
}

# Heuristic: lines in cheatsheet content that look like runnable commands.
_TOOL_HINT = re.compile(
    r'^\s*(sudo\s+)?('
    r'nmap|masscan|hping3|nikto|gobuster|ffuf|dirb|wfuzz|sqlmap|hydra|'
    r'john|hashcat|aircrack-ng|airmon-ng|airodump-ng|aireplay-ng|arpspoof|'
    r'ettercap|tcpdump|tshark|wireshark|netcat|nc|ncat|socat|curl|wget|'
    r'dig|host|nslookup|whois|theharvester|recon-ng|amass|subfinder|'
    r'enum4linux|smbclient|smbmap|rpcclient|ldapsearch|snmpwalk|'
    r'crackmapexec|cme|impacket|psexec|evil-winrm|responder|'
    r'metasploit|msfconsole|msfvenom|searchsploit|'
    r'python[23]?|perl|ruby|bash|powershell|pwsh|'
    r'openssl|ssh|scp|ftp|tftp|rsync|'
    r'setoolkit|volatility|binwalk|strings|objdump|gdb|radare2|r2'
    r')\b',
    re.IGNORECASE,
)

# A more permissive "looks like a shell command" fallback (has a flag or pipe).
_CMD_SHAPE = re.compile(r'^\s*[a-zA-Z][\w./-]+\s+(-{1,2}\w|\S+\s+-|\S+\s*\|)')


class CheatsheetOntology:
    """Queryable ontology over the cheatsheet library."""

    def __init__(self, data_path: Optional[str] = None, toolkit_root: Optional[str] = None):
        self.data_path = data_path or self._find_data_file()
        self.toolkit_root = toolkit_root or (
            os.path.dirname(self.data_path) if self.data_path else None
        )
        self._entries: Dict[str, Dict[str, Any]] = {}   # id -> entry
        self._by_category: Dict[str, List[str]] = {}    # category -> [ids]
        self._kind: Dict[str, str] = {}                 # id -> 'tool' | 'module'
        self.loaded = False
        self._load()

    # ------------------------------------------------------------------
    # Loading / indexing
    # ------------------------------------------------------------------

    @staticmethod
    def _find_data_file() -> Optional[str]:
        """Locate gacyber_toolkit/cheatsheet_data.json from common roots."""
        candidates = [
            os.path.join(os.getcwd(), "gacyber_toolkit", "cheatsheet_data.json"),
            os.path.join(os.getcwd(), "..", "gacyber_toolkit", "cheatsheet_data.json"),
            "/home/claude/work/Enterprise-Application/gacyber_toolkit/cheatsheet_data.json",
        ]
        # Also walk up from this file: backend/payloads/ -> repo root
        here = os.path.dirname(os.path.abspath(__file__))
        for up in range(1, 5):
            root = os.path.normpath(os.path.join(here, *([".."] * up)))
            candidates.append(os.path.join(root, "gacyber_toolkit", "cheatsheet_data.json"))
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return None

    def _load(self) -> None:
        if not self.data_path or not os.path.isfile(self.data_path):
            logger.warning("cheatsheet_data.json not found — ontology will be empty")
            return
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error("Failed to load cheatsheet data: %s", e)
            return

        for kind in ("tools", "modules"):
            for entry in data.get(kind, []):
                if not isinstance(entry, dict) or "id" not in entry:
                    continue
                eid = entry["id"]
                cat = (entry.get("category") or "uncategorized").strip().lower()
                self._entries[eid] = {
                    "id":       eid,
                    "title":    entry.get("title", eid),
                    "category": cat,
                    "kind":     kind[:-1],  # 'tool' / 'module'
                    "content":  entry.get("content", ""),
                }
                self._kind[eid] = kind[:-1]
                self._by_category.setdefault(cat, []).append(eid)

        self.loaded = True
        logger.info(
            "CheatsheetOntology loaded: %d entries across %d categories from %s",
            len(self._entries), len(self._by_category), self.data_path,
        )

    # ------------------------------------------------------------------
    # Command extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _looks_like_prose(line: str) -> bool:
        """Reject natural-language description lines that merely start with a tool name."""
        low = " " + line.lower() + " "
        prose_markers = (
            " is a ", " is an ", " are ", " to perform ", " which ", " that is ",
            " allows ", " enables ", " used to ", " will ", " can be ", " provides ",
            " cheat sheet", " description", " example:", " note:", " this ",
        )
        if any(m in low for m in prose_markers):
            # Still accept if it clearly contains a flag or placeholder (real cmd w/ inline note)
            if not re.search(r'(\s-{1,2}\w|\[[^\]]+\]|<[^>]+>|\||>>|\bhttp)', line):
                return True
        # A line that is many words and has no command-ish tokens is prose
        if len(line.split()) > 10 and not re.search(r'(\s-{1,2}\w|[|/<>\[\]]|=)', line):
            return True
        return False

    @staticmethod
    def _is_command_like(line: str) -> bool:
        """A matched-binary line must also carry a flag, path, placeholder, pipe, or be terse."""
        if re.search(r'(\s-{1,2}\w|\[[^\]]+\]|<[^>]+>|\||>>|>|\s/\S|\s\S+=|\.(sh|py|pl|rb|exe)\b)', line):
            return True
        return len(line.split()) <= 5   # terse invocations like "airmon-ng start wlan0"

    @classmethod
    def extract_commands(cls, content: str, max_commands: int = 25) -> List[str]:
        """
        Pull command-like lines out of a cheatsheet's free text.
        Conservative: prefers lines that start with a known tool binary AND look
        like a command (flag/path/placeholder/pipe or terse), rejecting prose.
        Falls back to lines with a clear command shape.
        """
        if not content:
            return []
        strong: List[str] = []
        weak: List[str] = []
        seen = set()
        for raw in content.splitlines():
            line = raw.strip().rstrip("\\").strip()
            if not line or len(line) < 4 or len(line) > 400:
                continue
            if line.endswith(":") or line.startswith(("#", "//", "*", "•")):
                continue
            if cls._looks_like_prose(line):
                continue
            key = line.lower()
            if key in seen:
                continue
            if _TOOL_HINT.match(line) and cls._is_command_like(line):
                seen.add(key)
                strong.append(line)
            elif _CMD_SHAPE.match(line) and not cls._looks_like_prose(line):
                seen.add(key)
                weak.append(line)
            if len(strong) >= max_commands:
                break
        commands = strong + weak
        return commands[:max_commands]

    @staticmethod
    def parameterize(command: str, target: str) -> str:
        """
        Substitute common target placeholders in a cheatsheet command with the
        authorized target. Replaces example IPs/hosts/placeholders.
        """
        if not target:
            return command
        subs = [
            (re.compile(r'\b(TARGET|target_ip|TARGET_IP|<target>|<ip>|<host>|RHOSTS?)\b'), target),
            (re.compile(r'\bexample\.com\b', re.IGNORECASE), target),
            (re.compile(r'\b10\.10\.10\.\d{1,3}\b'), target),
            (re.compile(r'\b192\.168\.\d{1,3}\.\d{1,3}\b'), target),
        ]
        out = command
        for pat, repl in subs:
            out = pat.sub(repl, out)
        return out

    # ------------------------------------------------------------------
    # Ontology queries (bounded ACTIONS)
    # ------------------------------------------------------------------

    def is_executable_category(self, category: str) -> bool:
        return category.strip().lower() not in _NON_EXECUTABLE_CATEGORIES

    def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        return self._entries.get(entry_id)

    def categories(self) -> List[str]:
        return sorted(self._by_category.keys())

    def resolve(
        self,
        phase: Optional[str] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        tool_id: Optional[str] = None,
        include_non_executable: bool = False,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Resolve cheatsheet entries matching the given constraints.
        Returns lightweight entry dicts (id, title, category, kind) — call
        get_entry() for full content.
        """
        candidate_ids: List[str] = []

        if tool_id:
            if tool_id in self._entries:
                candidate_ids = [tool_id]
        elif category:
            candidate_ids = list(self._by_category.get(category.strip().lower(), []))
        elif phase:
            cats = _PHASE_CATEGORY_MAP.get(phase, [])
            for cat in cats:
                candidate_ids.extend(self._by_category.get(cat, []))
        else:
            candidate_ids = list(self._entries.keys())

        # Keyword filter (title or content substring)
        if keyword:
            kw = keyword.lower()
            candidate_ids = [
                eid for eid in candidate_ids
                if kw in self._entries[eid]["title"].lower()
                or kw in self._entries[eid]["content"].lower()
            ]

        # De-dup, apply safety boundary
        results: List[Dict[str, Any]] = []
        seen = set()
        for eid in candidate_ids:
            if eid in seen:
                continue
            seen.add(eid)
            entry = self._entries[eid]
            if not include_non_executable and not self.is_executable_category(entry["category"]):
                continue
            results.append({
                "id":       entry["id"],
                "title":    entry["title"],
                "category": entry["category"],
                "kind":     entry["kind"],
            })
            if len(results) >= limit:
                break
        return results

    def resolve_commands(
        self,
        phase: str,
        target: str = "",
        limit_entries: int = 8,
        commands_per_entry: int = 6,
    ) -> List[Dict[str, Any]]:
        """
        For a phase, return real, parameterized commands drawn from matching
        cheatsheet entries. This is the core AIP interweave: pentest phase ->
        cheatsheet objects -> concrete command templates.
        """
        entries = self.resolve(phase=phase, limit=limit_entries)
        out: List[Dict[str, Any]] = []
        for meta in entries:
            full = self._entries[meta["id"]]
            cmds = self.extract_commands(full["content"], max_commands=commands_per_entry)
            for c in cmds:
                out.append({
                    "command":       self.parameterize(c, target),
                    "source_id":     full["id"],
                    "source_title":  full["title"],
                    "category":      full["category"],
                    "kind":          full["kind"],
                    "phase":         phase,
                })
        return out

    # ------------------------------------------------------------------
    # Ontology graph export (OBJECTS + LINKS)
    # ------------------------------------------------------------------

    def ontology_graph(self) -> Dict[str, Any]:
        """
        Export the ontology as objects + links for the frontend / AIP agent.
        objects: phases, categories, entries
        links:   phase->category, category->entry
        """
        objects: List[Dict[str, Any]] = []
        links: List[Dict[str, Any]] = []

        for phase, cats in _PHASE_CATEGORY_MAP.items():
            objects.append({"id": f"phase:{phase}", "type": "Phase", "label": phase})
            for cat in cats:
                if cat in self._by_category:
                    links.append({"from": f"phase:{phase}", "to": f"cat:{cat}", "rel": "contains"})

        for cat, ids in self._by_category.items():
            executable = self.is_executable_category(cat)
            objects.append({
                "id": f"cat:{cat}", "type": "Category", "label": cat,
                "executable": executable, "entry_count": len(ids),
            })
            for eid in ids:
                links.append({"from": f"cat:{cat}", "to": f"entry:{eid}", "rel": "contains"})

        for eid, entry in self._entries.items():
            objects.append({
                "id": f"entry:{eid}", "type": "CheatsheetEntry",
                "label": entry["title"], "kind": entry["kind"],
                "category": entry["category"],
                "executable": self.is_executable_category(entry["category"]),
            })

        return {
            "objects": objects,
            "links": links,
            "stats": {
                "phases": len(_PHASE_CATEGORY_MAP),
                "categories": len(self._by_category),
                "entries": len(self._entries),
                "non_executable_categories": sorted(_NON_EXECUTABLE_CATEGORIES),
            },
        }

    def stats(self) -> Dict[str, Any]:
        return {
            "loaded": self.loaded,
            "data_path": self.data_path,
            "entries": len(self._entries),
            "tools": sum(1 for k in self._kind.values() if k == "tool"),
            "modules": sum(1 for k in self._kind.values() if k == "module"),
            "categories": self.categories(),
        }
