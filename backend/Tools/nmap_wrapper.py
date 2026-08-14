"""
JAKAL Nmap Wrapper (CPENT Phase 2 - Scanning)

FIX (vs. earlier draft in the architecture doc):
The original built a shell command string and ran it with
`subprocess.run(cmd, shell=True, ...)`. Even with shlex.quote() on the
target, shell=True is an unnecessary risk surface for a tool whose whole
job is to take attacker-adjacent input (target strings). This version
builds an argument list and runs with shell=False, which is the
standard-practice way to avoid shell injection entirely.
"""

import logging
import subprocess
from typing import Any, Dict, Optional

from tools.authorization import check_authorization_and_scope

logger = logging.getLogger(__name__)

# CPENT-aligned scan profiles. Kept intentionally conservative by default
# (no -O OS-detection by default -- it requires raw sockets / root and is
# noisy; enable explicitly via extra_args if the engagement's RoE allows it).
_SCAN_PROFILES = {
    "quick": ["-T4", "-F"],
    "comprehensive": ["-sV", "-sC", "-T4"],
    "port_scan": ["-p-", "-T4"],
    "version": ["-sV"],
    "stealth": ["-sS", "-T2"],  # requires root/CAP_NET_RAW
}


def run_nmap(
    target: str,
    scan_type: str = "quick",
    operator_id: str = "system",
    extra_args: Optional[str] = None,
    timeout_seconds: int = 600,
    db=None,
) -> Dict[str, Any]:
    check_authorization_and_scope(target, "nmap_scan", operator_id, db=db)

    profile_args = _SCAN_PROFILES.get(scan_type, _SCAN_PROFILES["quick"])
    cmd = ["nmap", *profile_args, "-oX", "-"]  # XML to stdout for reliable parsing

    if extra_args:
        # Split on whitespace; still no shell involved, so no injection risk,
        # but log it since it's operator-supplied.
        cmd.extend(extra_args.split())
        logger.info("nmap extra_args supplied by operator: %s", extra_args)

    cmd.append(target)

    try:
        result = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "target": target,
            "scan_type": scan_type,
            "command": cmd,
            "stdout_xml": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        logger.error("nmap binary not found on PATH")
        return {"error": "nmap not installed", "target": target, "scan_type": scan_type}
    except subprocess.TimeoutExpired:
        logger.warning("nmap scan timed out after %ss for %s", timeout_seconds, target)
        return {"error": "scan timed out", "target": target, "scan_type": scan_type}
    except Exception as e:
        logger.error("nmap scan failed: %s", e)
        return {"error": str(e), "target": target, "scan_type": scan_type}
