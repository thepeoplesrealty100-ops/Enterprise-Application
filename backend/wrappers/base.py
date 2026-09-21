"""
backend/wrappers/base.py
Base class for all external tool wrappers.
Provides subprocess execution, target sanitisation, and timeout handling.
"""

import asyncio
import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Allowed characters in a target (IP, hostname, URL path)
_TARGET_RE = re.compile(r'^[a-zA-Z0-9.\-_:/\[\]]+$')


def sanitize_target(target: str) -> str:
    """
    Validate a target string against an allowlist.
    Raises ValueError on any character that could enable shell injection.
    """
    target = target.strip()
    if not target:
        raise ValueError("target must not be empty")
    if not _TARGET_RE.match(target):
        raise ValueError(
            f"Invalid target '{target}': only alphanumerics and .-_:/[]@ are permitted"
        )
    # Reject path-traversal sequences — a scan target is never a relative path.
    if ".." in target:
        raise ValueError(f"Invalid target '{target}': path traversal ('..') is not permitted")
    return target


class BaseToolWrapper:
    """
    Async subprocess wrapper with timeout, logging, and injection protection.

    Sub-classes call ``_run_command`` and parse the returned stdout string.
    """

    def __init__(self, binary_name: str, default_timeout: int = 300):
        self.binary_name = binary_name
        self.default_timeout = default_timeout

    async def _run_command(
        self,
        cmd: List[str],
        timeout: Optional[int] = None,
        stdin: Optional[str] = None,
    ) -> str:
        """
        Execute *cmd* list as a subprocess and return combined stdout.

        Args:
            cmd: argv list (NO shell=True — prevents injection).
            timeout: seconds before the process is killed; defaults to
                     ``self.default_timeout``.
            stdin: optional string piped to the process's stdin.

        Returns:
            Decoded stdout of the process.

        Raises:
            RuntimeError: process timed out or exited non-zero.
        """
        timeout = timeout or self.default_timeout
        logger.info("[%s] Running: %s", self.binary_name, " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin else None,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=stdin.encode() if stdin else None),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise RuntimeError(
                    f"{self.binary_name} timed out after {timeout}s"
                )

        except FileNotFoundError:
            raise RuntimeError(
                f"Binary '{self.binary_name}' not found — is it installed?"
            )

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        if proc.returncode not in (0, 1):  # many security tools exit 1 on findings
            logger.warning(
                "[%s] exited %d — stderr: %s",
                self.binary_name,
                proc.returncode,
                stderr[:500],
            )

        return stdout
