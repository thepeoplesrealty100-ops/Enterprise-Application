"""
JAKAL Security Agent – Scanning (CPENT Phase 2)

Performs authorized active scanning using Nmap (and optionally other tools).
Always runs behind the authorization / scope / insurance gate.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from tools.nmap_wrapper import run_nmap
from tools.authorization import check_authorization_and_scope

logger = logging.getLogger(__name__)


class ScanAgent:
    def __init__(self, db=None):
        self.db = db

    def scan(
        self,
        target: str,
        scan_type: str = "quick",
        operator_id: str = "system",
        extra_args: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute an authorized scan against the target.
        Returns structured results suitable for storage in pentest_runs / findings.
        """
        # Explicit gate (also called inside nmap_wrapper, but kept here for clarity)
        check_authorization_and_scope(target, "scan_agent_scan", operator_id)

        logger.info(f"[ScanAgent] Starting {scan_type} scan on {target}")

        nmap_result = run_nmap(
            target=target,
            scan_type=scan_type,
            operator_id=operator_id,
            extra_args=extra_args,
        )

        result = {
            "phase": "CPENT-Phase-2-Scanning",
            "target": target,
            "scan_type": scan_type,
            "nmap": nmap_result,
            "timestamp": datetime.utcnow().isoformat(),
            "operator_id": operator_id,
        }

        if self.db:
            try:
                self.db.insert_log(
                    {
                        "event": "SCAN_COMPLETED",
                        "action": f"nmap_{scan_type}",
                        "status": "success" if "error" not in nmap_result else "error",
                        "operator_id": operator_id,
                        "details": {"target": target, "scan_type": scan_type},
                    }
                )
            except Exception as e:
                logger.warning(f"Could not write scan log: {e}")

        return result

    def port_sweep(self, target: str, operator_id: str = "system") -> Dict[str, Any]:
        """Convenience method for a full port scan (still authorized)."""
        return self.scan(target, scan_type="port_scan", operator_id=operator_id)

    def service_version(self, target: str, operator_id: str = "system") -> Dict[str, Any]:
        """Service and version detection only."""
        return self.scan(target, scan_type="version", operator_id=operator_id)
