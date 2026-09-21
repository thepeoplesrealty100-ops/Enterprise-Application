"""
JAKAL Security Agent - Reporting

Aggregates findings from ReconAgent / EnumAgent / WebAgent (and, if present,
QuantumEngine.quantum_risk_panel for the optional quantum-readiness section)
into one structured report: JSON for the API/dashboard, and Markdown for a
human-readable deliverable.

CVSS note: this assigns a *qualitative* severity-to-score mapping
(critical/high/medium/low/info -> a representative CVSS v3.1 base score
range), not a computed CVSS vector. Real CVSS scoring requires the actual
attack vector, complexity, privileges required, etc. per finding, which
varies case by case -- this gives a reasonable ballpark for prioritization,
not a substitute for scoring each CVE-backed finding properly by hand or
pulling its published NVD score.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Representative CVSS v3.1 base score midpoint per qualitative severity band,
# per the official NVD/FIRST qualitative severity ranges.
_SEVERITY_SCORE_MAP = {
    "critical": 9.5,   # 9.0 - 10.0
    "high": 7.5,       # 7.0 - 8.9
    "medium": 5.5,     # 4.0 - 6.9
    "low": 2.5,        # 0.1 - 3.9
    "info": 0.0,
}


class ReportAgent:
    def __init__(self, db_manager=None, orchestrator=None):
        self.db = db_manager
        self.orchestrator = orchestrator  # AgentOrchestrator, for MITRE mapping

    def generate(
        self,
        target: str,
        recon_results: Optional[Dict[str, Any]] = None,
        enum_results: Optional[Dict[str, Any]] = None,
        web_results: Optional[Dict[str, Any]] = None,
        quantum_panel: Optional[Dict[str, Any]] = None,
        operator_id: str = "system",
    ) -> Dict[str, Any]:
        findings = self._collect_findings(recon_results, enum_results, web_results)
        findings.sort(key=lambda f: f["score"], reverse=True)

        attack_mappings = []
        if self.orchestrator and recon_results:
            try:
                attack_mappings = self.orchestrator.map_to_attack_framework(recon_results)
            except Exception as e:
                logger.warning(f"MITRE mapping failed: {e}")

        report = {
            "target": target,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": operator_id,
            "summary": self._severity_counts(findings),
            "findings": findings,
            "mitre_attack_mappings": attack_mappings,
            "quantum_readiness": quantum_panel,  # optional, only if caller passes it
        }

        if self.db:
            self.db.insert_log({
                "event": "REPORT_GENERATED",
                "action": "report_agent_generate",
                "status": "success",
                "operator_id": operator_id,
                "details": {"target": target, "finding_count": len(findings)},
            })

        return report

    def to_markdown(self, report: Dict[str, Any]) -> str:
        lines = [
            f"# Security Assessment Report",
            f"",
            f"**Target:** `{report['target']}`  ",
            f"**Generated:** {report['generated_at']}  ",
            f"**Operator:** {report['generated_by']}",
            f"",
            f"## Executive Summary",
            f"",
        ]
        counts = report["summary"]
        lines.append("| Severity | Count |")
        lines.append("|---|---|")
        for sev in ("critical", "high", "medium", "low", "info"):
            lines.append(f"| {sev.capitalize()} | {counts.get(sev, 0)} |")
        lines.append("")

        lines.append("## Findings")
        lines.append("")
        if not report["findings"]:
            lines.append("_No findings recorded._")
        for f in report["findings"]:
            lines.append(f"### [{f['severity'].upper()}] {f['title']}")
            lines.append(f"")
            lines.append(f"- **Source:** {f['source']}")
            lines.append(f"- **Approx. CVSS band:** {f['score']}")
            if f.get("description"):
                lines.append(f"- **Description:** {f['description']}")
            if f.get("remediation"):
                lines.append(f"- **Remediation:** {f['remediation']}")
            lines.append("")

        if report.get("mitre_attack_mappings"):
            lines.append("## MITRE ATT&CK Mapping")
            lines.append("")
            lines.append("| Tactic | Technique | Finding |")
            lines.append("|---|---|---|")
            for m in report["mitre_attack_mappings"]:
                lines.append(f"| {m.get('tactic')} | {m.get('technique_id')} - {m.get('technique_name')} | {m.get('finding')} |")
            lines.append("")

        if report.get("quantum_readiness"):
            lines.append("## Quantum Readiness (illustrative)")
            lines.append("")
            lines.append(report["quantum_readiness"].get("recommendation", ""))
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _collect_findings(
        self,
        recon_results: Optional[Dict[str, Any]],
        enum_results: Optional[Dict[str, Any]],
        web_results: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        if recon_results:
            for vuln in recon_results.get("vulnerabilities", []):
                sev = (vuln.get("severity") or "info").lower()
                findings.append({
                    "source": "recon/nuclei",
                    "title": vuln.get("name", "Unnamed finding"),
                    "severity": sev,
                    "score": _SEVERITY_SCORE_MAP.get(sev, 0.0),
                    "description": vuln.get("description"),
                    "remediation": None,
                })
            for port in recon_results.get("open_ports", []):
                sev = port.get("severity", "low")
                findings.append({
                    "source": "recon/nmap",
                    "title": f"Open port {port['port']}/{port.get('protocol', 'tcp')}: {port.get('service')}",
                    "severity": sev,
                    "score": _SEVERITY_SCORE_MAP.get(sev, 0.0),
                    "description": f"{port.get('product', '')} {port.get('version', '')}".strip() or None,
                    "remediation": "Close port if not required; restrict via firewall/security group if required.",
                })

        if enum_results:
            zt = enum_results.get("dns_zone_transfer", {})
            if zt.get("vulnerable_to_axfr"):
                findings.append({
                    "source": "enum/dns",
                    "title": "DNS zone transfer (AXFR) permitted",
                    "severity": "critical",
                    "score": _SEVERITY_SCORE_MAP["critical"],
                    "description": zt.get("finding"),
                    "remediation": "Restrict AXFR to authorized secondary nameservers only.",
                })
            snmp = enum_results.get("snmp", {})
            if snmp.get("public_community_accessible"):
                findings.append({
                    "source": "enum/snmp",
                    "title": "SNMP 'public' community string readable",
                    "severity": "medium",
                    "score": _SEVERITY_SCORE_MAP["medium"],
                    "description": snmp.get("finding"),
                    "remediation": "Disable default community strings; use SNMPv3 with authentication.",
                })
            smb = enum_results.get("smb_shares", {})
            if smb.get("anonymous_access"):
                findings.append({
                    "source": "enum/smb",
                    "title": "Anonymous SMB share listing permitted",
                    "severity": "medium",
                    "score": _SEVERITY_SCORE_MAP["medium"],
                    "description": f"{len(smb.get('shares_found', []))} share(s) visible without authentication",
                    "remediation": "Disable anonymous/guest SMB access.",
                })

        if web_results:
            for h in web_results.get("security_headers", {}).get("missing", []):
                findings.append({
                    "source": "web/headers",
                    "title": f"Missing security header: {h['header']}",
                    "severity": h["severity"],
                    "score": _SEVERITY_SCORE_MAP.get(h["severity"], 0.0),
                    "description": None,
                    "remediation": f"Add `{h['header']}` response header.",
                })
            for p in web_results.get("exposed_paths", []):
                findings.append({
                    "source": "web/exposed-path",
                    "title": p["finding"],
                    "severity": p["severity"],
                    "score": _SEVERITY_SCORE_MAP.get(p["severity"], 0.0),
                    "description": p["url"],
                    "remediation": "Remove or block public access to this path.",
                })
            dl = web_results.get("directory_listing", {})
            if dl.get("finding"):
                findings.append({
                    "source": "web/directory-listing",
                    "title": "Directory listing enabled",
                    "severity": "medium",
                    "score": _SEVERITY_SCORE_MAP["medium"],
                    "description": dl["finding"],
                    "remediation": "Disable directory listing (e.g. `Options -Indexes` in Apache).",
                })

        return findings

    @staticmethod
    def _severity_counts(findings: List[Dict[str, Any]]) -> Dict[str, int]:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for f in findings:
            sev = f.get("severity", "info")
            if sev in counts:
                counts[sev] += 1
        return counts
