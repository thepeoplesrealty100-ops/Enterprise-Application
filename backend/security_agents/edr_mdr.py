"""
JAKAL Advanced EDR / MDR Base
==============================
Scope note, read this first: a real EDR/MDR *agent* means kernel-level
telemetry hooks (Windows minifilters/ETW, macOS Endpoint Security
Framework, Linux eBPF probes), a fleet-wide collector, and a detection
engine running on every monitored endpoint. That is a multi-person,
multi-month systems-programming project per OS, not something this module
pretends to be. What's implemented here is the layer a real EDR agent's
alerts would actually feed into: a playbook library (structured incident-
response procedures, seeded from publicly documented frameworks) and an
execution/audit tracker for running a playbook against a real or simulated
incident and recording what happened. If you later stand up an actual EDR
agent, point its alert webhook at `/api/edr/alert` (not yet built) to
auto-suggest a playbook; for now, playbook selection and execution is
operator-driven via the API below.

Playbook categories and their NIST SP 800-61 phase names are public,
widely-taught incident-response taxonomy -- not proprietary content.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# NIST SP 800-61-style phases, used to tag each playbook step.
PHASES = ["preparation", "detection_analysis", "containment", "eradication", "recovery", "post_incident"]

DEFAULT_PLAYBOOKS: List[Dict[str, Any]] = [
    {
        "key": "suspicious_login",
        "name": "Suspicious Login / Impossible Travel",
        "category": "identity",
        "steps": [
            {"phase": "detection_analysis", "action": "Correlate login geo/IP/device against the user's baseline; confirm anomaly is not a known VPN/travel case."},
            {"phase": "containment", "action": "Force re-authentication and step-up MFA on the session; do not yet revoke, to avoid tipping off an active attacker mid-investigation."},
            {"phase": "containment", "action": "Review and revoke any OAuth grants / active tokens issued during the anomalous session."},
            {"phase": "eradication", "action": "Reset credentials if compromise is confirmed; rotate any API keys the account could reach."},
            {"phase": "recovery", "action": "Re-enable normal access once containment steps are verified; notify the user."},
            {"phase": "post_incident", "action": "Log timeline and indicators to agent_logs; update detection thresholds if this was a false positive."},
        ],
    },
    {
        "key": "phishing_quarantine",
        "name": "Phishing / Malicious Email Quarantine",
        "category": "email",
        "steps": [
            {"phase": "detection_analysis", "action": "Pull the reported message; extract sender, links, and attachment hashes for triage."},
            {"phase": "containment", "action": "Quarantine the message org-wide (all recipients) by sender/hash/URL match."},
            {"phase": "containment", "action": "Identify and isolate any endpoint(s) where a link was clicked or attachment opened."},
            {"phase": "eradication", "action": "Run an AV/EDR scan on affected endpoints; remove any dropped payload."},
            {"phase": "recovery", "action": "Force password reset for any users who submitted credentials to the phishing page."},
            {"phase": "post_incident", "action": "Add indicators to the email gateway blocklist; notify affected users and track click-through metrics for the awareness-training module."},
        ],
    },
    {
        "key": "ransomware_containment",
        "name": "Ransomware Containment",
        "category": "malware",
        "steps": [
            {"phase": "containment", "action": "Isolate affected host(s) from the network immediately (disable NIC / block at switch), do not power off (preserves memory for forensics)."},
            {"phase": "containment", "action": "Disable shared/service credentials that were active on the affected host to stop lateral spread."},
            {"phase": "detection_analysis", "action": "Identify the ransomware family/variant if possible and scope which other hosts share the same exposure."},
            {"phase": "eradication", "action": "Rebuild affected hosts from known-clean images rather than attempting in-place cleanup."},
            {"phase": "recovery", "action": "Validate backup integrity BEFORE restoring; restore from the most recent verified-clean backup."},
            {"phase": "post_incident", "action": "Root-cause the initial access vector; file with cyber-insurance if a policy is on file (see insurance_policies table)."},
        ],
    },
    {
        "key": "data_exfiltration",
        "name": "Data Exfiltration",
        "category": "dlp",
        "steps": [
            {"phase": "detection_analysis", "action": "Identify the data flow: source system, destination, volume, and classification of data involved."},
            {"phase": "containment", "action": "Block the egress channel (IP/domain/protocol) at the firewall or proxy."},
            {"phase": "detection_analysis", "action": "Determine scope of data exposed; check against any regulated-data classifications (PII/PHI/PCI)."},
            {"phase": "eradication", "action": "Revoke the credentials or process that initiated the transfer."},
            {"phase": "post_incident", "action": "If regulated data was exposed, flag for legal/compliance review and breach-notification timeline (see compliance_axiom module)."},
        ],
    },
    {
        "key": "privileged_account_compromise",
        "name": "Privileged Account Compromise",
        "category": "identity",
        "steps": [
            {"phase": "containment", "action": "Disable the privileged account immediately; rotate any credentials it could access."},
            {"phase": "detection_analysis", "action": "Audit recent privileged actions taken by the account for unauthorized changes."},
            {"phase": "detection_analysis", "action": "Check for lateral movement or new persistence mechanisms (scheduled tasks, new admin accounts, SSH keys)."},
            {"phase": "eradication", "action": "Remove any unauthorized persistence found."},
            {"phase": "recovery", "action": "Re-provision access under least-privilege; require hardware MFA for re-enablement."},
            {"phase": "post_incident", "action": "Review why the compromise wasn't caught sooner; tighten alerting on privileged-account anomalies."},
        ],
    },
    {
        "key": "anomalous_process_execution",
        "name": "Anomalous / Malicious Process Execution (EDR Alert)",
        "category": "endpoint",
        "steps": [
            {"phase": "containment", "action": "Isolate the host from the network while preserving the running process for analysis."},
            {"phase": "detection_analysis", "action": "Collect the process tree, loaded modules, and any network connections the process opened."},
            {"phase": "detection_analysis", "action": "Check the binary hash against known-good/known-bad lists; sandbox-detonate if unknown (see VM Orchestrator)."},
            {"phase": "eradication", "action": "Terminate the process and remove its persistence mechanism (registry run key, cron, launch agent, etc.)."},
            {"phase": "recovery", "action": "Return host to service once clean; monitor closely for 24-48h."},
            {"phase": "post_incident", "action": "Write a detection rule for this pattern to catch recurrence."},
        ],
    },
]


class EdrMdrEngine:
    def __init__(self, db_manager=None):
        self.db = db_manager

    def seed_default_playbooks(self, operator_id: str = "system") -> Dict[str, Any]:
        if not self.db:
            return {"status": "error", "error": "no database configured"}
        created = 0
        for pb in DEFAULT_PLAYBOOKS:
            if not self.db.get_playbook_by_key(pb["key"]):
                self.db.insert_playbook(pb["key"], pb["name"], pb["category"], pb["steps"])
                created += 1
        self.db.insert_log({
            "event": "PLAYBOOKS_SEEDED", "action": "edr_mdr_seed", "status": "success",
            "operator_id": operator_id, "details": {"created": created, "total": len(DEFAULT_PLAYBOOKS)},
        })
        return {"status": "ok", "created": created, "total": len(DEFAULT_PLAYBOOKS)}

    def list_playbooks(self) -> List[Dict[str, Any]]:
        if not self.db:
            return DEFAULT_PLAYBOOKS
        return self.db.list_playbooks()

    def start_execution(self, playbook_key: str, context: str, operator_id: str = "system") -> Dict[str, Any]:
        if not self.db:
            return {"status": "error", "error": "no database configured"}
        pb = self.db.get_playbook_by_key(playbook_key)
        if not pb:
            return {"status": "error", "error": f"unknown playbook '{playbook_key}'"}
        exec_id = self.db.insert_playbook_execution(pb["id"], context, operator_id)
        self.db.insert_log({
            "event": "PLAYBOOK_EXECUTION_STARTED", "action": "edr_mdr_execute", "status": "in_progress",
            "operator_id": operator_id, "details": {"playbook": playbook_key, "context": context, "execution_id": exec_id},
        })
        return {"status": "started", "execution_id": exec_id, "playbook": pb["name"], "steps": pb["steps"]}

    def complete_step(self, execution_id: int, step_index: int, notes: str = "", operator_id: str = "system") -> Dict[str, Any]:
        if not self.db:
            return {"status": "error", "error": "no database configured"}
        result = self.db.update_playbook_execution_step(execution_id, step_index, notes)
        self.db.insert_log({
            "event": "PLAYBOOK_STEP_COMPLETED", "action": "edr_mdr_step", "status": "success",
            "operator_id": operator_id, "details": {"execution_id": execution_id, "step_index": step_index},
        })
        return result

    def finish_execution(self, execution_id: int, operator_id: str = "system") -> Dict[str, Any]:
        if not self.db:
            return {"status": "error", "error": "no database configured"}
        result = self.db.finish_playbook_execution(execution_id)
        self.db.insert_log({
            "event": "PLAYBOOK_EXECUTION_COMPLETED", "action": "edr_mdr_finish", "status": "success",
            "operator_id": operator_id, "details": {"execution_id": execution_id},
        })
        return result
