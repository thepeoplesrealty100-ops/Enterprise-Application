"""
backend/wrappers/nmap_wrapper.py
Async wrapper for Nmap port scanning.
Replaces the older backend/Tools/nmap_wrapper.py with the unified BaseToolWrapper pattern.
"""

import logging
import re
from typing import List, Optional

from .base import BaseToolWrapper, sanitize_target

logger = logging.getLogger(__name__)

# Parse lines like:
#   80/tcp   open  http    nginx 1.14.0
_PORT_RE = re.compile(
    r'^(\d+)/(\w+)\s+(\w+)\s+(\S+)(?:\s+(.+))?$'
)


class NmapWrapper(BaseToolWrapper):
    """Run nmap port scans and parse service-version output."""

    def __init__(self):
        super().__init__(binary_name="nmap", default_timeout=300)

    async def run_port_scan(
        self,
        target: str,
        ports: str = "1-1000",
        extra_flags: Optional[List[str]] = None,
        timeout: int = 300,
    ) -> dict:
        """
        Service-version scan on *target*.

        Args:
            target: IP or hostname (sanitised).
            ports: port spec e.g. "22,80,443" or "1-65535".
            extra_flags: additional nmap flags (no shell expansion — list items only).
            timeout: process timeout in seconds.

        Returns:
            dict with keys ``target``, ``ports`` (list of dicts), ``open_count``.
        """
        target = sanitize_target(target)

        cmd = [
            self.binary_name,
            "-sV",          # version detection
            "-p", ports,
            "--open",       # only open ports
            target,
        ]

        if extra_flags:
            cmd.extend(extra_flags)

        raw = await self._run_command(cmd, timeout=timeout)

        open_ports: list = []
        for line in raw.splitlines():
            match = _PORT_RE.match(line.strip())
            if match and match.group(3) == "open":
                open_ports.append({
                    "port":     int(match.group(1)),
                    "protocol": match.group(2),
                    "state":    match.group(3),
                    "service":  match.group(4),
                    "version":  (match.group(5) or "").strip(),
                })

        return {
            "target": target,
            "ports": open_ports,
            "open_count": len(open_ports),
        }
