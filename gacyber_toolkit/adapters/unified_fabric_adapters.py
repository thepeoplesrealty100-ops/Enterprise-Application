"""
Adapters for Unified Security Fabric micro-modules.
These adapters are intentionally lightweight and do not execute scripts by default.
They provide metadata and a safe invocation surface for the backend unified_fabric package.
"""
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
GAC_PATH = REPO_ROOT / 'gacyber_toolkit'

MODULE_SCRIPTS = {
    'mdr': str(GAC_PATH / '03-Enumeration'),
    'zero_trust': str(GAC_PATH / 'Resources'),
    'sase': str(GAC_PATH / 'Resources'),
    'pam': str(GAC_PATH / 'Resources'),
    'dns_filter': str(GAC_PATH / 'Scripts') if (GAC_PATH / 'Scripts').exists() else str(GAC_PATH),
    'email_filter': str(GAC_PATH / 'Scripts') if (GAC_PATH / 'Scripts').exists() else str(GAC_PATH),
    'dlp': str(GAC_PATH / 'Resources'),
}


def get_module_script_path(module_key: str) -> Dict[str, str]:
    return {'module_key': module_key, 'script_path': MODULE_SCRIPTS.get(module_key)}
