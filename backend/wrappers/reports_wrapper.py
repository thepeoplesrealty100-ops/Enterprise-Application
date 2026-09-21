"""
backend/wrappers/reports_wrapper.py
Aggregates multi-tool scan results into a unified JAKAL report dict.
No subprocess required — pure Python aggregation logic.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Severity weights used for risk-score calculation
_SEVERITY_WEIGHT: Dict[str, int] = {
    "critical": 10,
    "high":     7,
    "medium":   4,
    "low":      1,
    "info":     0,
}


class ReportsWrapper:
    """Aggregate and summarise scan results from multiple tool wrappers."""

    def generate_summary(
        self,
        scan_id: str,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build a consolidated report from a list of tool result dicts.

        Each element of *results* should contain at minimum:
            - ``tool``     (str)  — which wrapper produced it
            - ``target``   (str)  — scanned target
            - ``findings`` (list) — list of finding dicts (may be empty)

        Returns a report dict with:
            - ``scan_id``
            - ``generated_at``
            - ``targets``        — unique list of scanned targets
            - ``tools_run``      — list of tool names
            - ``total_findings``
            - ``risk_score``     — weighted sum based on severity
            - ``findings_by_tool``
            - ``high_priority``  — findings with severity critical/high
        """
        all_findings: list = []
        findings_by_tool: Dict[str, list] = {}
        tools_run: list = []
        targets: set = set()

        for result in results:
            tool = result.get("tool", "unknown")
            target = result.get("target", "unknown")
            findings = result.get("findings", [])

            targets.add(target)
            tools_run.append(tool)
            findings_by_tool[tool] = findings
            all_findings.extend(findings)

        risk_score = 0
        for finding in all_findings:
            sev = str(finding.get("severity", "info")).lower()
            risk_score += _SEVERITY_WEIGHT.get(sev, 0)

        high_priority = [
            f for f in all_findings
            if str(f.get("severity", "")).lower() in ("critical", "high")
        ]

        summary = {
            "scan_id":          scan_id,
            "generated_at":     datetime.utcnow().isoformat(),
            "targets":          sorted(targets),
            "tools_run":        tools_run,
            "total_findings":   len(all_findings),
            "risk_score":       risk_score,
            "findings_by_tool": findings_by_tool,
            "high_priority":    high_priority,
        }

        logger.info(
            "[ReportsWrapper] scan %s — %d findings, risk score %d",
            scan_id, len(all_findings), risk_score,
        )
        return summary
