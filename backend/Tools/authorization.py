"""
JAKAL / GACyber Tool Kit - Authorization, Scope & Insurance Gate
Mandatory check for EVERY network-facing action.
CPENT-aligned: Ensures written authorization, defined scope, and active insurance
before any recon, scanning, enumeration, or further phases.

All activity must remain strictly within defined scope, written RoE,
and active cyber-liability / professional-indemnity coverage.
"""

from datetime import datetime
from typing import Optional, Dict, Any
import json
import logging

# Relative import works when run from backend/
try:
    from database import DuckDBManager
except ImportError:
    from backend.database import DuckDBManager  # fallback for different layouts

logger = logging.getLogger(__name__)
db = DuckDBManager()


def check_authorization_and_scope(
    target: str,
    action: str,
    operator_id: str = "system",
    require_insurance: bool = True,
) -> Dict[str, Any]:
    """
    Real-time legal, scope, and insurance validation.
    Raises PermissionError if any check fails.
    Returns a dict with authorization metadata on success.
    """
    if not target or not str(target).strip():
        raise PermissionError("Empty or invalid target supplied.")

    target = str(target).strip()

    # Load active scopes
    try:
        scopes = db.query(
            "SELECT id, client_name, scope_definition, start_date, end_date, status "
            "FROM scopes WHERE status = 'active'"
        )
    except Exception as e:
        logger.error(f"Failed to query scopes: {e}")
        scopes = []

    # Load active insurance
    try:
        insurance = db.query(
            "SELECT id, policy_number, provider, coverage_amount, expiry, status "
            "FROM insurance_policies "
            "WHERE status = 'active' AND expiry > ?",
            (datetime.utcnow(),),
        )
    except Exception as e:
        logger.error(f"Failed to query insurance: {e}")
        insurance = []

    # Simple scope matching (expand with ipaddress / domain parsing as needed)
    in_scope = False
    matched_scope = None
    for s in scopes:
        # s[2] is scope_definition (string or JSON of IPs/domains)
        scope_def = str(s[2]) if s[2] else ""
        if target in scope_def or any(
            part.strip() and target.startswith(part.strip())
            for part in scope_def.replace(",", " ").split()
        ):
            in_scope = True
            matched_scope = {
                "scope_id": s[0],
                "client_name": s[1],
                "scope_definition": scope_def,
            }
            break

    has_insurance = len(insurance) > 0
    insurance_info = None
    if has_insurance:
        ins = insurance[0]
        insurance_info = {
            "policy_number": ins[1],
            "provider": ins[2],
            "expiry": str(ins[4]),
        }

    if not in_scope:
        db.insert_log(
            {
                "event": "AUTHORIZATION_DENIED",
                "action": action,
                "status": "blocked",
                "operator_id": operator_id,
                "details": {
                    "target": target,
                    "reason": "target outside authorized scope",
                },
            }
        )
        raise PermissionError(
            f"Target '{target}' is outside authorized scope. Operation blocked."
        )

    if require_insurance and not has_insurance:
        db.insert_log(
            {
                "event": "AUTHORIZATION_DENIED",
                "action": action,
                "status": "blocked",
                "operator_id": operator_id,
                "details": {
                    "target": target,
                    "reason": "no active insurance policy found",
                },
            }
        )
        raise PermissionError(
            "No active cyber-liability / professional-indemnity insurance found. "
            "Operation blocked."
        )

    # Success path
    auth_record = {
        "authorized": True,
        "timestamp": datetime.utcnow().isoformat(),
        "target": target,
        "action": action,
        "operator_id": operator_id,
        "matched_scope": matched_scope,
        "insurance": insurance_info,
    }

    db.insert_log(
        {
            "event": "AUTHORIZATION_GRANTED",
            "action": action,
            "status": "approved",
            "operator_id": operator_id,
            "details": auth_record,
        }
    )

    logger.info(
        f"Authorization granted: action={action} target={target} operator={operator_id}"
    )
    return auth_record


def require_authorization(target: str, action: str, operator_id: str = "system"):
    """
    Decorator-style helper (can also be used as a plain function call).
    """
    return check_authorization_and_scope(target, action, operator_id)


# Convenience for scripts that only need a boolean
def is_authorized(target: str, action: str, operator_id: str = "system") -> bool:
    try:
        check_authorization_and_scope(target, action, operator_id)
        return True
    except PermissionError:
        return False
