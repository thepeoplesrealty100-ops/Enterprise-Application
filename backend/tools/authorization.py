"""
JAKAL Authorization Gate
========================
Mandatory scope / legal / insurance check that every network-facing
tool wrapper and agent must call before touching a target.

v2.1 upgrade: Every authorization decision (grant AND deny) is now
PQC-signed with ML-DSA-65 via PQCAuditManager and persisted to the
pqc_audit_log table — creating an immutable, cryptographically-verified
authorization trail.

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

# ── PQC audit manager (lazy-initialised; optional) ─────────────────────────
_pqc_manager = None

def _get_pqc():
    global _pqc_manager
    if _pqc_manager is None:
        try:
            from crypto.pqc_manager import PQCAuditManager
            _pqc_manager = PQCAuditManager()
        except Exception as e:
            logger.warning("PQCAuditManager unavailable in authorization gate: %s", e)
    return _pqc_manager


def _pqc_sign_authorization(
    action: str,
    target: str,
    operator_id: str,
    decision: str,
    reason: str,
    db=None,
) -> Optional[str]:
    """
    PQC-sign an authorization decision and persist to pqc_audit_log.
    Returns entry_id or None if PQC unavailable.
    """
    pqc = _get_pqc()
    if not pqc:
        return None
    try:
        payload = {
            "action": action,
            "target": target,
            "operator_id": operator_id,
            "decision": decision,
            "reason": reason,
        }
        signed = pqc.sign_agent_action(
            agent_id="authorization-gate",
            action_payload=payload,
            operator_id=operator_id,
        )
        if db:
            import json
            db.insert_pqc_audit_entry({
                "entry_id":     signed["entry_id"],
                "agent_id":     "authorization-gate",
                "operator_id":  operator_id,
                "action_type":  f"authorization_{decision.lower()}",
                "action_detail": json.dumps(payload),
                "payload_hash": signed["payload_hash"],
                "pqc_signature":signed["pqc_signature"],
                "algorithm":    signed["algorithm"],
                "public_key":   signed["public_key"],
            })
        return signed["entry_id"]
    except Exception as e:
        logger.warning("PQC signing of authorization decision failed: %s", e)
        return None


# ══════════════════════════════════════════════════════════════════════════

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


def get_authorization_status(target: str, db=None) -> dict:
    """
    Read-only scope + insurance status for `target` -- the same real
    CIDR/domain-suffix containment logic check_authorization_and_scope()
    enforces, but as a pure query: no PQC signature, no pqc_audit_log
    write, no AuthorizationError raise. This exists so a display/
    visibility feature (v3.0 Phase 4.2's approval-context enrichment --
    see ExploitAgent.get_enriched_approval_context()) can show "is this
    target actually authorized" WITHOUT generating a spurious signed
    audit entry every time an operator views a payload; only an actual
    execution attempt through check_authorization_and_scope() should
    produce an audit-trail decision.

    Fails closed: any exception while determining status is reported as
    authorized=False with a reason, never silently defaulting to True.

    Returns {"in_scope": bool, "has_insurance": bool, "authorized": bool,
    "reason": Optional[str]} -- reason is None only when authorized.
    """
    if db is None:
        from database import get_db_manager
        db = get_db_manager()
    try:
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
            _, _, scope_definition, *_ = row
            for entry in str(scope_definition).split(","):
                entry = entry.strip()
                if entry and _target_matches_entry(target, entry):
                    in_scope = True
                    break
            if in_scope:
                break

        has_insurance = len(insurance_rows) > 0
        authorized = in_scope and has_insurance

        reason = None
        if not authorized:
            reason_parts = []
            if not in_scope:
                reason_parts.append("target outside authorized scope")
            if not has_insurance:
                reason_parts.append("no active insurance policy on file")
            reason = "; ".join(reason_parts)

        return {"in_scope": in_scope, "has_insurance": has_insurance,
                "authorized": authorized, "reason": reason}
    except Exception as e:
        logger.warning("Authorization status check failed for target '%s': %s", target, e)
        return {"in_scope": False, "has_insurance": False, "authorized": False,
                "reason": f"authorization status check failed: {e}"}


def check_authorization_and_scope(
    target: str,
    action: str,
    operator_id: str,
    db=None,
) -> dict:
    """
    Real-time legal, scope, and insurance validation.
    Raises AuthorizationError (blocks execution) if any check fails.

    Every decision (grant AND deny) is PQC-signed with ML-DSA-65 and
    persisted to pqc_audit_log for immutable audit trail.

    `db` should be a DuckDBManager instance (see database.py). Passed in
    rather than imported at module scope to avoid circular imports and
    to make this function easy to unit test with a fake db.
    """
    if db is None:
        from database import DuckDBManager, get_db_manager
        db = get_db_manager()

    now = datetime.now(timezone.utc)

    status = get_authorization_status(target, db=db)

    if not status["authorized"]:
        reason_str = status["reason"] or "not authorized"

        # PQC-sign the denial
        pqc_entry_id = _pqc_sign_authorization(
            action=action, target=target, operator_id=operator_id,
            decision="DENIED", reason=reason_str, db=db,
        )

        db.insert_log({
            "event": "AUTHORIZATION_DENIED",
            "action": action,
            "status": "blocked",
            "operator_id": operator_id,
            "details": {
                "target": target,
                "reason": reason_str,
                "pqc_entry_id": pqc_entry_id,
            },
        })
        raise AuthorizationError(
            f"Authorization denied for target '{target}': {reason_str}."
        )

    # PQC-sign the grant
    pqc_entry_id = _pqc_sign_authorization(
        action=action, target=target, operator_id=operator_id,
        decision="GRANTED", reason="scope and insurance validated", db=db,
    )

    db.insert_log({
        "event": "AUTHORIZATION_GRANTED",
        "action": action,
        "status": "approved",
        "operator_id": operator_id,
        "details": {
            "target": target,
            "pqc_entry_id": pqc_entry_id,
        },
    })
    return {
        "authorized": True,
        "timestamp": now.isoformat(),
        "pqc_entry_id": pqc_entry_id,
    }
