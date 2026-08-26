"""
backend/wrappers
External security-tool wrapper package.
All wrappers inherit from BaseToolWrapper for consistent subprocess handling.
"""

from .base import BaseToolWrapper, sanitize_target
from .nuclei_wrapper import NucleiWrapper
from .gobuster_wrapper import GobusterWrapper
from .sqlmap_wrapper import SqlmapWrapper
from .nmap_wrapper import NmapWrapper
from .reports_wrapper import ReportsWrapper

__all__ = [
    "BaseToolWrapper",
    "sanitize_target",
    "NucleiWrapper",
    "GobusterWrapper",
    "SqlmapWrapper",
    "NmapWrapper",
    "ReportsWrapper",
]
