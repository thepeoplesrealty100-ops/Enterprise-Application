"""
JAKAL Quantum Compliance Axiom
================================
Despite the name (kept from the product concept doc), there is nothing
quantum about this module -- it's a straightforward compliance-mapping and
report-generation engine. Renaming is a one-line change in app.py + the
blueprint if you'd rather call it "Compliance Engine" internally; the
route/label is kept as-is here since it's user-facing branding, not a
technical claim.

What it does:
  - Maps active scopes, findings (from ReportAgent-style output), and
    insurance/audit-log state onto the top-level categories of a handful
    of publicly documented compliance frameworks (SOC 2, HIPAA Security
    Rule, NIST CSF, GDPR). Category names and structure are public
    taxonomies; this module does not embed or claim to reproduce the full
    control text of any framework, and does NOT certify compliance -- it
    produces a coverage/gap summary for a human to review.
  - Persists reports so other modules (report_agent, EDR/MDR playbooks)
    can pull the latest compliance snapshot for a target/engagement.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Public top-level taxonomies only -- no proprietary control text.
FRAMEWORKS: Dict[str, List[str]] = {
    "SOC2": ["Security", "Availability", "Processing Integrity", "Confidentiality", "Privacy"],
    "HIPAA": ["Administrative Safeguards", "Physical Safeguards", "Technical Safeguards", "Organizational Requirements"],
    "NIST_CSF": ["Govern", "Identify", "Protect", "Detect", "Respond", "Recover"],
    "GDPR": [
        "Lawfulness, Fairness & Transparency", "Purpose Limitation", "Data Minimization",
        "Accuracy", "Storage Limitation", "Integrity & Confidentiality", "Accountability",
    ],
}

# Heuristic mapping from finding sources / events (as produced elsewhere in
# this codebase -- see report_agent.py's `source` field, and agent_logs
# `event` values) onto the categories above. This is a starting point for a
# human reviewer, not an automated certification.
_FINDING_SOURCE_TO_CATEGORY = {
    "recon/nmap": {"NIST_CSF": "Identify", "SOC2": "Security"},
    "recon/nuclei": {"NIST_CSF": "Detect", "SOC2": "Security"},
    "enum/dns": {"NIST_CSF": "Protect", "SOC2": "Security"},
    "enum/snmp": {"NIST_CSF": "Protect", "SOC2": "Security"},
    "enum/smb": {"NIST_CSF": "Protect", "SOC2": "Security", "HIPAA": "Technical Safeguards"},
    "web/headers": {"NIST_CSF": "Protect", "SOC2": "Security"},
    "web/exposed-path": {"NIST_CSF": "Protect", "SOC2": "Confidentiality"},
    "web/directory-listing": {"NIST_CSF": "Protect", "SOC2": "Confidentiality"},
}


class ComplianceAxiom:
    def __init__(self, db_manager=None):
        self.db = db_manager

    def available_frameworks(self) -> Dict[str, List[str]]:
        return dict(FRAMEWORKS)

    def generate_report(
        self,
        framework: str,
        findings: Optional[List[Dict[str, Any]]] = None,
        scope_id: Optional[int] = None,
        operator_id: str = "system",
    ) -> Dict[str, Any]:
        framework = framework.upper()
        if framework not in FRAMEWORKS:
            return {"status": "error", "error": f"unknown framework. choose from {list(FRAMEWORKS)}"}

        findings = findings or []
        categories = {cat: {"status": "not_assessed", "findings": []} for cat in FRAMEWORKS[framework]}

        for f in findings:
            mapping = _FINDING_SOURCE_TO_CATEGORY.get(f.get("source", ""), {})
            cat = mapping.get(framework)
            if cat and cat in categories:
                categories[cat]["findings"].append({
                    "title": f.get("title"),
                    "severity": f.get("severity"),
                })

        for cat, data in categories.items():
            if not data["findings"]:
                data["status"] = "no_findings"
            elif any(fi["severity"] in ("critical", "high") for fi in data["findings"]):
                data["status"] = "gap_high"
            else:
                data["status"] = "gap_low"

        insurance_active = False
        scope_active = False
        if self.db:
            now = datetime.now(timezone.utc)
            insurance_active = len(self.db.query(
                "SELECT id FROM insurance_policies WHERE status='active' AND expiry > ?", (now,)
            )) > 0
            if scope_id is not None:
                scope_active = len(self.db.query(
                    "SELECT id FROM scopes WHERE id = ? AND status='active' AND start_date <= ? AND end_date >= ?",
                    (scope_id, now, now),
                )) > 0

        report = {
            "framework": framework,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": operator_id,
            "scope_id": scope_id,
            "governance": {
                "active_insurance_on_file": insurance_active,
                "active_scope_for_engagement": scope_active,
            },
            "categories": categories,
            "disclaimer": (
                "Automated coverage summary based on technical findings only. "
                "Does not constitute a compliance certification or legal attestation -- "
                "administrative, physical, and process controls must be assessed separately."
            ),
        }

        if self.db:
            report_id = self.db.insert_compliance_report(framework, scope_id, report)
            report["report_id"] = report_id
            self.db.insert_log({
                "event": "COMPLIANCE_REPORT_GENERATED", "action": "compliance_axiom_generate",
                "status": "success", "operator_id": operator_id,
                "details": {"framework": framework, "scope_id": scope_id},
            })

        return report

    def to_markdown(self, report: Dict[str, Any]) -> str:
        lines = [
            f"# Compliance Coverage Report -- {report['framework']}",
            "",
            f"**Generated:** {report['generated_at']}  ",
            f"**Operator:** {report['generated_by']}",
            "",
            f"> {report['disclaimer']}",
            "",
            "## Governance",
            f"- Active insurance on file: {'yes' if report['governance']['active_insurance_on_file'] else 'no'}",
            f"- Active engagement scope: {'yes' if report['governance']['active_scope_for_engagement'] else 'no'}",
            "",
            "## Category Coverage",
            "",
        ]
        for cat, data in report["categories"].items():
            lines.append(f"### {cat} -- `{data['status']}`")
            if data["findings"]:
                for f in data["findings"]:
                    lines.append(f"- [{f['severity'].upper()}] {f['title']}")
            else:
                lines.append("_No findings mapped to this category._")
            lines.append("")
        return "\n".join(lines)
