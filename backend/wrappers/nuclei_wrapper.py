"""
backend/wrappers/nuclei_wrapper.py
Async wrapper for the Nuclei vulnerability scanner.
"""

import json
import logging
from typing import List, Optional

from .base import BaseToolWrapper, sanitize_target

logger = logging.getLogger(__name__)


class NucleiWrapper(BaseToolWrapper):
    """Run Nuclei template-based scans and parse JSON-line output."""

    def __init__(self):
        super().__init__(binary_name="nuclei", default_timeout=600)

    async def run_scan(
        self,
        target: str,
        templates: Optional[List[str]] = None,
        severity: Optional[str] = None,
        timeout: int = 600,
    ) -> dict:
        """
        Execute a Nuclei scan against *target*.

        Args:
            target: IP, hostname, or URL (sanitised before use).
            templates: list of template paths/tags (e.g. ["cves", "exposures"]).
                       Defaults to the default Nuclei template library.
            severity: comma-separated severity filter e.g. "critical,high".
            timeout: process timeout in seconds.

        Returns:
            dict with keys ``target``, ``findings`` (list), ``total``.
        """
        target = sanitize_target(target)

        cmd = [
            self.binary_name,
            "-target", target,
            "-json",          # machine-readable output per line
            "-silent",        # suppress banner
            "-no-interactsh", # avoid OOB lookups in automated runs
        ]

        if templates:
            for tmpl in templates:
                cmd += ["-t", tmpl]

        if severity:
            cmd += ["-severity", severity]

        raw = await self._run_command(cmd, timeout=timeout)

        findings: list = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                findings.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Non-JSON nuclei line: %s", line[:120])

        return {
            "target": target,
            "findings": findings,
            "total": len(findings),
        }
