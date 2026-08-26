"""
backend/wrappers/gobuster_wrapper.py
Async wrapper for Gobuster directory/file brute-forcing.
"""

import logging
from typing import List, Optional

from .base import BaseToolWrapper, sanitize_target

logger = logging.getLogger(__name__)


class GobusterWrapper(BaseToolWrapper):
    """Run Gobuster ``dir`` mode and parse discovered paths."""

    def __init__(self):
        super().__init__(binary_name="gobuster", default_timeout=300)

    async def run_dir_scan(
        self,
        url: str,
        wordlist: str = "/usr/share/wordlists/dirb/common.txt",
        extensions: Optional[List[str]] = None,
        threads: int = 20,
        timeout: int = 300,
    ) -> dict:
        """
        Directory/file brute-force against *url*.

        Args:
            url: target URL (sanitised).
            wordlist: absolute path to a wordlist file.
            extensions: file extensions to probe, e.g. ["php", "html", "js"].
            threads: concurrent goroutines (default 20).
            timeout: process timeout in seconds.

        Returns:
            dict with keys ``url``, ``paths`` (list of str), ``total``.
        """
        url = sanitize_target(url)

        cmd = [
            self.binary_name, "dir",
            "-u", url,
            "-w", wordlist,
            "-t", str(threads),
            "--no-progress",   # cleaner output for parsing
            "-q",              # quiet — only show findings
        ]

        if extensions:
            cmd += ["-x", ",".join(extensions)]

        raw = await self._run_command(cmd, timeout=timeout)

        paths: List[str] = []
        for line in raw.splitlines():
            line = line.strip()
            # Gobuster lines: "/<path> (Status: 200) [Size: 1234]"
            if line and "(Status:" in line:
                path = line.split()[0]
                paths.append(path)

        return {
            "url": url,
            "paths": paths,
            "total": len(paths),
        }
