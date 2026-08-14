"""
JAKAL Authorization Gate
========================
Mandatory scope / legal / insurance check that every network-facing
tool wrapper and agent must call before touching a target.

FIX (vs. earlier draft in the architecture doc):
The original scope check used `target in str(scope_row)`, a plain
substring match. That is exploitable: a scope of "example.com" would
also match "evil-example.com" or "example.com.attacker.net", and an
IP scope of "10.0.0.5" would match "110.0.0.50". This version does
real domain-suffix matching and real CIDR containment checks.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class AuthorizationError(PermissionError):
    """Raised when a target/action is not authorized. Caught by API layer -> HTTP 403."""


@dataclass
class ScopeEntry:
    id: int
    client_name: str
    scope_definition: str  # comma-separated list of CIDRs and/or domain suffixes
    start_date: datetime
    end_date: datetime
    status: str


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _target_matches_entry(target: str, entry_value: str) -> bool:
    """
    Real containment check, not substring matching.

    - If entry_value parses as a CIDR/IP network, and target is an IP,
      check real network containment.
    - Otherwise treat entry_value as a domain suffix: target must be
      exactly that domain OR a strict subdomain of it (dot-bounded),
      never merely containing the string.
    """
    entry_value = entry_value.strip().lower()
    target = target.strip().lower()

    # --- IP / CIDR path ---
    if _is_ip(target):
        try:
            network = ipaddress.ip_network(entry_value, strict=False)
            return ipaddress.ip_address(target) in network
        except ValueError:
            return False  # entry_value wasn't a network spec; no match for an IP target

    # --- Domain path ---
    # Strip scheme/path if a full URL was passed as the target.
    domain = target
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    domain = domain.split("/", 1)[0].split(":", 1)[0]

    if domain == entry_value:
        return True
    # Strict subdomain match: must end with ".entry_value", not just contain it.
    return domain.endswith("." + entry_value)


def check_authorization_and_scope(
    target: str,
    action: str,
    operator_id: str,
    db=None,
) -> dict:
    """
    Real-time legal, scope, and insurance validation.
    Raises AuthorizationError (blocks execution) if any check fails.

    `db` should be a DuckDBManager instance (see database.py). Passed in
    rather than imported at module scope to avoid circular imports and
    to make this function easy to unit test with a fake db.
    """
    if db is None:
        from database import DuckDBManager
        db = DuckDBManager()

    now = datetime.now(timezone.utc)

    scope_rows = db.query(
        "SELECT id, client_name, scope_definition, start_date, end_date, status "
        "FROM scopes WHERE status = 'active' AND start_date <= ? AND end_date >= ?",
        (now, now),
    )

    insurance_rows = db.query(
        "SELECT id FROM insurance_policies WHERE status = 'active' AND expiry > ?",
        (now,),
    )

    in_scope = False
    for row in scope_rows:
        # row layout matches the SELECT above
        _, _, scope_definition, *_ = row
        for entry in str(scope_definition).split(","):
            entry = entry.strip()
            if not entry:
                continue
            if _target_matches_entry(target, entry):
                in_scope = True
                break
        if in_scope:
            break

    has_insurance = len(insurance_rows) > 0

    if not in_scope or not has_insurance:
        reason = []
        if not in_scope:
            reason.append("target outside authorized scope")
        if not has_insurance:
            reason.append("no active insurance policy on file")
        reason_str = "; ".join(reason)

        db.insert_log({
            "event": "AUTHORIZATION_DENIED",
            "action": action,
            "status": "blocked",
            "operator_id": operator_id,
            "details": {"target": target, "reason": reason_str},
        })
        raise AuthorizationError(
            f"Authorization denied for target '{target}': {reason_str}."
        )

    db.insert_log({
        "event": "AUTHORIZATION_GRANTED",
        "action": action,
        "status": "approved",
        "operator_id": operator_id,
        "details": {"target": target},
    })
    return {"authorized": True, "timestamp": now.isoformat()}
