"""
backend/wrappers/sqlmap_wrapper.py
Async wrapper for sqlmap SQL-injection detection.
AUTHORIZATION GATE: caller must have passed scope + insurance check
before invoking any method on this class.
"""

import logging
import re
from typing import Optional

from .base import BaseToolWrapper, sanitize_target

logger = logging.getLogger(__name__)

_INJECTABLE_RE = re.compile(
    r"Parameter: (.+?) \(.+?\) is vulnerable", re.IGNORECASE
)


class SqlmapWrapper(BaseToolWrapper):
    """Run sqlmap in batch mode and parse injectable-parameter output."""

    def __init__(self):
        super().__init__(binary_name="sqlmap", default_timeout=300)

    async def run_scan(
        self,
        target_url: str,
        risk: int = 1,
        level: int = 1,
        data: Optional[str] = None,
        timeout: int = 300,
    ) -> dict:
        """
        Execute a sqlmap scan.

        Args:
            target_url: URL to test (sanitised).
            risk: sqlmap risk level (1–3).
            level: sqlmap test level (1–5).
            data: POST body if testing a POST endpoint.
            timeout: process timeout in seconds.

        Returns:
            dict with keys ``target``, ``injectable_params`` (list), ``raw_lines`` (list).
        """
        target_url = sanitize_target(target_url)
        risk  = max(1, min(3, risk))
        level = max(1, min(5, level))

        cmd = [
            self.binary_name,
            "-u", target_url,
            f"--risk={risk}",
            f"--level={level}",
            "--batch",           # non-interactive
            "--random-agent",    # randomise user-agent
            "--output-dir=/tmp/sqlmap_out",
        ]

        if data:
            cmd += ["--data", data]

        raw = await self._run_command(cmd, timeout=timeout)

        injectable: list = []
        raw_lines: list = []
        for line in raw.splitlines():
            raw_lines.append(line)
            match = _INJECTABLE_RE.search(line)
            if match:
                injectable.append(match.group(1))

        return {
            "target": target_url,
            "injectable_params": injectable,
            "raw_lines": raw_lines,
        }
