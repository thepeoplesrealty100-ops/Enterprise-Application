"""
backend/repository.py
In-memory scan repository for the JAKAL API.
Stores active scan records keyed by scan ID.
"""

from typing import Dict, Optional, Any
from datetime import datetime
import uuid


class ScanRepository:
    """Thread-safe in-memory store for scan lifecycle tracking."""

    def __init__(self):
        self._scans: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_scan(
        self,
        target: str,
        scan_type: str = "comprehensive",
        operator_id: str = "system",
    ) -> Dict[str, Any]:
        scan_id = str(uuid.uuid4())
        record = {
            "scan_id": scan_id,
            "target": target,
            "scan_type": scan_type,
            "operator_id": operator_id,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "findings": [],
            "report": None,
        }
        self._scans[scan_id] = record
        return record

    def update_scan_status(
        self,
        scan_id: str,
        status: str,
        findings: Optional[list] = None,
        report: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        record = self._scans.get(scan_id)
        if record is None:
            return None
        record["status"] = status
        record["updated_at"] = datetime.utcnow().isoformat()
        if findings is not None:
            record["findings"] = findings
        if report is not None:
            record["report"] = report
        return record

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        return self._scans.get(scan_id)

    def list_scans(self, operator_id: Optional[str] = None) -> list:
        scans = list(self._scans.values())
        if operator_id:
            scans = [s for s in scans if s.get("operator_id") == operator_id]
        return sorted(scans, key=lambda s: s["created_at"], reverse=True)

    def delete_scan(self, scan_id: str) -> bool:
        if scan_id in self._scans:
            del self._scans[scan_id]
            return True
        return False


# Singleton instance used across the application
scan_repo = ScanRepository()
