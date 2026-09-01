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

v2.7: NIST finalized SP 800-61 Revision 3 in April 2025, retiring the
four-phase (Preparation/Detection&Analysis/Containment-Eradication-Recovery/
Post-Incident) lifecycle in favor of mapping IR onto NIST CSF 2.0's six
functions (Govern/Identify/Protect/Detect/Respond/Recover) -- IR itself
covers Detect/Respond/Recover, with the rest treated as ongoing risk
management rather than incident-triggered activity. The 8 playbooks added
in v2.7 (SUPPLY_CHAIN_PLAYBOOKS below) tag each step with `csf2_function`
alongside the existing `phase` field for backward compatibility with the
6 v2.4 playbooks above and every existing test/consumer that reads `phase`.
Steps that map onto a real, callable action in routers/response.py also
carry an `automation_key` (e.g. "ioc_block", "isolate_host") so a UI can
offer an "Execute" button next to that step instead of it being purely
descriptive -- and a `d3fend_technique` tag (d3fend.mitre.org) for the ones
with a real MITRE D3FEND defensive-technique mapping.
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

# v2.7 — CSF 2.0 / D3FEND-tagged playbooks, appended to the v2.4 set above.
SUPPLY_CHAIN_PLAYBOOKS: List[Dict[str, Any]] = [
    {
        "key": "supply_chain_compromise",
        "name": "Software Supply Chain / Dependency Compromise",
        "category": "supply_chain",
        "steps": [
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Run POST /api/vault/eas-rd/scan to get a live OSV.dev CVE match against every pinned dependency; identify which finding triggered this."},
            {"phase": "containment", "csf2_function": "Respond", "d3fend_technique": "D3-OTF", "automation_key": "ioc_block",
             "action": "Block any known-malicious package registry mirror or typosquat domain identified in the advisory."},
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Diff the affected package's lockfile hash against the last known-good build to confirm whether the compromise is upstream or a local tamper."},
            {"phase": "eradication", "csf2_function": "Respond",
             "action": "Pin to the patched version (or vendor a known-good fork) and rebuild from a clean CI runner, not an in-place `pip install --upgrade`."},
            {"phase": "recovery", "csf2_function": "Recover",
             "action": "Re-run the EAS R&D scan to confirm zero findings before returning the pipeline to normal cadence."},
            {"phase": "post_incident", "csf2_function": "Recover",
             "action": "File the advisory (CVE/GHSA id) plus remediation timeline for SBOM/compliance records (see compliance_axiom module)."},
        ],
    },
    {
        "key": "cloud_account_compromise",
        "name": "Cloud Provider / SaaS Admin Account Compromise",
        "category": "cloud_identity",
        "steps": [
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Pull the cloud provider's IAM activity log for the account; look for new access keys, changed MFA devices, or new trust-policy grants."},
            {"phase": "containment", "csf2_function": "Respond", "d3fend_technique": "D3-EI", "automation_key": "isolate_host",
             "action": "Suspend the compromised principal's active sessions and revoke all its access keys/tokens immediately."},
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Enumerate every resource the account could reach (IAM policy simulator) and check each for unauthorized changes."},
            {"phase": "eradication", "csf2_function": "Respond",
             "action": "Remove any new roles/policies/service principals the attacker created; rotate every secret the account had access to."},
            {"phase": "recovery", "csf2_function": "Recover",
             "action": "Re-provision the account under least-privilege with hardware-token MFA before re-enabling."},
            {"phase": "post_incident", "csf2_function": "Recover",
             "action": "Review CloudTrail/Activity-Log retention and alerting thresholds that should have caught this sooner."},
        ],
    },
    {
        "key": "ddos_response",
        "name": "Distributed Denial of Service",
        "category": "availability",
        "steps": [
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Confirm volumetric/protocol/application-layer classification from traffic telemetry (packets/sec, unique source count, target port/path concentration)."},
            {"phase": "containment", "csf2_function": "Respond", "d3fend_technique": "D3-OTF", "automation_key": "ioc_block",
             "action": "Block the highest-confidence attacking source ranges at the edge/CDN; enable rate limiting on the affected endpoint."},
            {"phase": "containment", "csf2_function": "Respond",
             "action": "Engage upstream DDoS scrubbing (CDN/ISP) if volumetric attack exceeds local mitigation capacity."},
            {"phase": "recovery", "csf2_function": "Recover",
             "action": "Gradually restore normal traffic acceptance; watch for a second-wave attack once mitigation is lifted."},
            {"phase": "post_incident", "csf2_function": "Recover",
             "action": "Capture attack signature for future auto-detection; review capacity headroom and edge mitigation coverage."},
        ],
    },
    {
        "key": "insider_threat_data_staging",
        "name": "Insider Threat — Data Staging / Exfil Prep",
        "category": "insider",
        "steps": [
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Correlate DLP alerts with unusual bulk file access/download volume from a single user in a short window."},
            {"phase": "containment", "csf2_function": "Respond", "d3fend_technique": "D3-CQ", "automation_key": "quarantine_artifact",
             "action": "Quarantine the staged archive/export before it leaves the environment; do not yet confront the user (preserve evidence)."},
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Involve HR/Legal per your insider-threat policy before any account action — this phase has employment-law implications outside security's remit."},
            {"phase": "containment", "csf2_function": "Respond",
             "action": "Once cleared by HR/Legal, restrict the user's data-egress channels (USB, personal cloud drives, webmail) pending investigation outcome."},
            {"phase": "post_incident", "csf2_function": "Recover",
             "action": "Document chain of custody for any evidence collected; route findings to HR/Legal for final disposition."},
        ],
    },
    {
        "key": "iot_ot_device_compromise",
        "name": "IoT / OT Device Compromise",
        "category": "iot_ot",
        "steps": [
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Identify the device via passive fingerprinting (avoid active scanning on OT/ICS gear — it can crash fragile embedded controllers)."},
            {"phase": "containment", "csf2_function": "Respond", "d3fend_technique": "D3-NI", "automation_key": "isolate_host",
             "action": "Isolate the device to its own VLAN/segment rather than powering it off — many OT devices lose state or require a slow, careful restart."},
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Check firmware version against the vendor's advisory list; OT/ICS devices are frequently unpatched for years by design constraint, not neglect."},
            {"phase": "eradication", "csf2_function": "Respond",
             "action": "Apply vendor-validated firmware update on a maintenance window, or if unavailable, add compensating network-layer controls."},
            {"phase": "recovery", "csf2_function": "Recover",
             "action": "Re-integrate only after safety-system sign-off if the device is part of a physical-process control loop."},
        ],
    },
    {
        "key": "emergency_vulnerability_patch",
        "name": "Vulnerability-Driven Emergency Patch",
        "category": "vulnerability_management",
        "steps": [
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Triggered by a CRITICAL/HIGH finding from POST /api/vault/eas-rd/scan or /api/pentest/run — confirm exploitability against this deployment's actual configuration (not every CVE match is reachable)."},
            {"phase": "containment", "csf2_function": "Respond",
             "action": "If a patch isn't immediately available, apply a compensating control (WAF rule, feature flag, network ACL) to reduce exposure."},
            {"phase": "eradication", "csf2_function": "Respond",
             "action": "Apply the vendor patch through the normal change-management pipeline, expedited — not a manual hotfix on the live host."},
            {"phase": "recovery", "csf2_function": "Recover",
             "action": "Re-scan to confirm the finding is resolved; remove the compensating control only once the real fix is verified."},
            {"phase": "post_incident", "csf2_function": "Recover",
             "action": "Track mean-time-to-patch for this finding class; feed into the next EAS R&D cadence review."},
        ],
    },
    {
        "key": "wireless_rogue_ap",
        "name": "Rogue Access Point / Evil Twin",
        "category": "wireless",
        "steps": [
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Confirm via the Wireless module (/api/wireless/*) survey: compare observed BSSID/ESSID pairs against the known-good AP inventory."},
            {"phase": "containment", "csf2_function": "Respond", "d3fend_technique": "D3-NI", "automation_key": "isolate_host",
             "action": "Physically locate and disconnect the rogue AP if on-premises; if it's an evil-twin broadcasting a spoofed SSID, alert users and disable auto-connect for that SSID via MDM."},
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Identify any client devices that associated with the rogue AP — their traffic during that window should be treated as potentially intercepted."},
            {"phase": "eradication", "csf2_function": "Respond",
             "action": "Force credential rotation for any user who authenticated to a captive portal on the rogue AP."},
            {"phase": "post_incident", "csf2_function": "Recover",
             "action": "Add continuous rogue-AP detection to the wireless module's recurring survey cadence."},
        ],
    },
    {
        "key": "pqc_crypto_agility_incident",
        "name": "PQC Crypto-Agility Incident (Algorithm Compromise / Deprecation)",
        "category": "cryptography",
        "steps": [
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Triggered by either a real cryptanalytic break of a deployed algorithm, OR a compliance trigger: NIST IR 8547 designates RSA-2048/ECC P-256-class algorithms for deprecation by 2030 and disallowed by 2035 — confirm which case this is."},
            {"phase": "detection_analysis", "csf2_function": "Detect",
             "action": "Inventory every place the affected algorithm is used (see /api/crypto/keys, /api/crypto/pqc/status) — TLS, at-rest encryption, code signing, VPN."},
            {"phase": "containment", "csf2_function": "Respond",
             "action": "If this is an active compromise (not a compliance deadline), rotate every key using the affected algorithm immediately via /api/crypto/keys/rotate; this platform already defaults to ML-DSA-65 (FIPS 204) for signing, so the audit chain itself is unaffected by an RSA/ECC break."},
            {"phase": "eradication", "csf2_function": "Respond",
             "action": "Migrate remaining classical-only algorithm usage to the FIPS 203/204/205 (ML-KEM/ML-DSA/SLH-DSA) family, or a hybrid classical+PQC scheme during the transition window, per NIST IR 8547's phased-transition guidance."},
            {"phase": "recovery", "csf2_function": "Recover",
             "action": "Re-verify the full pqc_audit_log chain (/api/crypto/pqc/verify-chain) after migration to confirm no signatures were silently downgraded."},
            {"phase": "post_incident", "csf2_function": "Recover",
             "action": "Update the crypto-agility inventory and re-run this playbook proactively ahead of the next NIST deprecation milestone rather than waiting for a compromise."},
        ],
    },
]

DEFAULT_PLAYBOOKS = DEFAULT_PLAYBOOKS + SUPPLY_CHAIN_PLAYBOOKS


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
