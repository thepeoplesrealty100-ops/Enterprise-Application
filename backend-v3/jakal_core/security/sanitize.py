"""Target / command sanitization (preserves and hardens the reviewed pattern).

The reviewed ``wrappers/base.py`` already did the right thing: allowlist target
characters, reject ``..``, and never use ``shell=True``. This module keeps that
and adds an argv allowlist for sandbox exec so a caller cannot smuggle shell
metacharacters into a container command.
"""
from __future__ import annotations

import re
import shlex

_TARGET_RE = re.compile(r"^[a-zA-Z0-9.\-_:/\[\]]+$")
_SHELL_METACHARS = set(";|&$`><\n\r\\!*?(){}")
# argv[0] basenames that are interpreters/shells — refused for sandbox exec even
# when passed argv-style, since `sh -c '…'` re-introduces a shell vector.
_INTERPRETER_DENYLIST = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish",
     "python", "python3", "perl", "ruby", "php", "node", "env",
     "nc", "ncat", "netcat", "socat"}
)


def sanitize_target(target: str) -> str:
    target = target.strip()
    if not target:
        raise ValueError("target must not be empty")
    if len(target) > 255:
        raise ValueError("target too long")
    if not _TARGET_RE.match(target):
        raise ValueError(f"invalid target {target!r}: character allowlist violation")
    if ".." in target:
        raise ValueError(f"invalid target {target!r}: path traversal is not permitted")
    return target


def validate_sandbox_command(command: str) -> list[str]:
    """Return a safe argv list for container exec, or raise.

    Rejects any shell metacharacter — the command is executed argv-style
    (``exec``), never through a shell, so injection has no vector.
    """
    if not command or not command.strip():
        raise ValueError("empty command")
    if any(ch in _SHELL_METACHARS for ch in command):
        raise ValueError("command contains shell metacharacters — refused")
    argv = shlex.split(command)
    if not argv:
        raise ValueError("command parsed to empty argv")
    binary = argv[0].rsplit("/", 1)[-1]
    if binary in _INTERPRETER_DENYLIST:
        raise ValueError(f"interpreter/shell {binary!r} is not permitted in sandbox exec")
    return argv
