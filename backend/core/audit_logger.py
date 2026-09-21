"""
backend/core/audit_logger.py
============================
Immutable Audit Trail Logger

Provides compliance-grade, tamper-evident audit logging with:
  • SHA3-256 hash chaining (detect tampering)
  • Immutable record appends
  • SSE event streaming
  • PQC-compatible (ML-DSA-65 signatures)

Enterprise patterns from: CISA recommendations, NIST SP 800-53

RECONCILIATION FIX: this class originally targeted a `pqc_audit_log` table
with columns (event_id, event_type, timestamp, actor, resource, action,
result, details, hash_value, prev_hash) -- but the real pqc_audit_log
table (backend/database.py) has an entirely different, unrelated schema
(id, entry_id, timestamp, agent_id, operator_id, action_type,
action_detail, payload_hash, pqc_signature, algorithm, public_key,
chain_index, prev_hash), used by crypto/pqc_manager.py for ML-DSA-65
signed agent actions. Every INSERT/SELECT against pqc_audit_log below was
therefore hitting the wrong table with the wrong column names -- silently,
since _persist_event() swallowed the resulting exception in a bare
try/except: pass, so this "immutable audit trail" was in practice
persisting zero rows.

Fixed to target `resonance_audit_trail` (also added by this same parallel
build, in database.py, and actually shaped for this purpose) instead. That
table's columns (event_id, event_type, isolation_id, policy_id, actor,
status, event_data, signature_hmac, timestamp) don't have a 1:1 match for
this class's generic (action, resource, details, hash_value, prev_hash)
fields either, so those are packed into event_data as JSON -- resource is
additionally best-effort mirrored into isolation_id/policy_id when the
caller's `details` dict names one, so isolation- and policy-scoped queries
stay possible without an ALTER TABLE (DuckDB 0.10.0's ALTER TABLE ADD
COLUMN has a separately-confirmed WAL-replay crash against a persistent
.duckdb file -- see database.py's approval_requests comment for the
reproduction).
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuditEvent(BaseModel):
    """Single auditable event."""
    event_id: str = Field(...)
    event_type: str  # e.g., "isolation_enforced", "approval_requested"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: Optional[str] = None  # Operator ID or system
    resource: Optional[str] = None  # What was affected
    action: str  # What was done
    result: str = "success"  # success, failure, pending
    details: Optional[Dict[str, Any]] = None
    
    # Audit chain
    hash_value: Optional[str] = None  # SHA3-256 of this record
    prev_hash: Optional[str] = None  # SHA3-256 of previous record (chain link)


class AuditLogger:
    """
    Provides immutable audit logging for the platform.
    All records are append-only; deletions trigger audit alerts.
    """
    
    def __init__(self, db_manager):
        """
        Args:
            db_manager: DuckDBManager instance
        """
        self.db = db_manager
        self._sse_handlers = []  # List of SSE event handlers
    
    def log(
        self,
        event_type: str,
        action: str,
        actor: Optional[str] = None,
        resource: Optional[str] = None,
        result: str = "success",
        details: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        """
        Log an audit event (append-only).
        
        Args:
            event_type: Category (e.g., "isolation_enforced")
            action: Action description (e.g., "host_isolation")
            actor: Who performed the action (operator ID)
            resource: What was affected (hostname, IP, etc.)
            result: Outcome (success, failure, pending)
            details: Additional context (dict)
            **kwargs: Additional fields (merged into details)
        
        Returns:
            event_id of the logged event
        """
        import uuid
        
        event_id = str(uuid.uuid4())
        
        # Merge kwargs into details
        if details is None:
            details = {}
        details.update(kwargs)
        
        # Create audit event
        event = AuditEvent(
            event_id=event_id,
            event_type=event_type,
            actor=actor,
            resource=resource,
            action=action,
            result=result,
            details=details,
        )
        
        # Get previous hash for chain
        prev_hash = self._get_latest_hash()
        event.prev_hash = prev_hash or "GENESIS"
        
        # Compute hash for this record
        event.hash_value = self._compute_hash(event)
        
        # Persist to database
        self._persist_event(event)
        
        # Emit SSE event
        self._emit_sse(event)
        
        return event_id
    
    def _row_to_event(self, r: tuple) -> Dict[str, Any]:
        """Unpack one resonance_audit_trail row -- (id, event_id, event_type,
        isolation_id, policy_id, actor, status, event_data, signature_hmac,
        timestamp) -- back into this class's logical AuditEvent shape."""
        payload = json.loads(r[7] or "{}")
        return {
            "id": r[0],
            "event_id": r[1],
            "event_type": r[2],
            "isolation_id": r[3],
            "policy_id": r[4],
            "actor": r[5],
            "result": r[6],
            "resource": payload.get("resource"),
            "action": payload.get("action"),
            "details": payload.get("details", {}),
            "hash_value": payload.get("hash_value"),
            "prev_hash": payload.get("prev_hash"),
            "signature_hmac": r[8],
            "timestamp": r[9],
        }

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single audit event."""
        try:
            rows = self.db.conn.execute(
                """
                SELECT id, event_id, event_type, isolation_id, policy_id, actor, status, event_data, signature_hmac, timestamp
                FROM resonance_audit_trail
                WHERE event_id = ?
                LIMIT 1
                """,
                (event_id,),
            ).fetchall()

            if rows:
                return self._row_to_event(rows[0])
        except Exception:
            pass

        return None
    
    def list_events(
        self,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
        result: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Query audit events with filters.
        
        Args:
            event_type: Filter by event type
            actor: Filter by actor (operator)
            result: Filter by result (success, failure)
            limit: Max results
            offset: Pagination offset
        
        Returns:
            List of audit events
        """
        clauses = []
        params = []

        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if result:
            clauses.append("status = ?")
            params.append(result)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT id, event_id, event_type, isolation_id, policy_id, actor, status, event_data, signature_hmac, timestamp
            FROM resonance_audit_trail
            {where}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        try:
            rows = self.db.conn.execute(query, params).fetchall()
            return [self._row_to_event(r) for r in rows]
        except Exception:
            return []
    
    def verify_chain(self) -> Dict[str, Any]:
        """
        Verify the integrity of the audit chain.
        Returns { valid: bool, first_broken_id: int, reason: str }
        """
        try:
            rows = self.db.conn.execute(
                """
                SELECT id, event_id, event_type, isolation_id, policy_id, actor, status, event_data, signature_hmac, timestamp
                FROM resonance_audit_trail
                ORDER BY id ASC
                """
            ).fetchall()

            expected_prev = "GENESIS"

            for r in rows:
                event = self._row_to_event(r)
                row_id, hash_value, prev_hash = event["id"], event["hash_value"], event["prev_hash"]

                # Check chain link
                if prev_hash != expected_prev:
                    return {
                        "valid": False,
                        "first_broken_id": row_id,
                        "reason": f"prev_hash mismatch at {row_id}",
                    }

                # Verify hash (recompute from the same fields _compute_hash used)
                recomputed = self._compute_hash_from_row(event, prev_hash)
                if recomputed != hash_value:
                    return {
                        "valid": False,
                        "first_broken_id": row_id,
                        "reason": f"hash mismatch at {row_id}",
                    }

                expected_prev = hash_value

            return {
                "valid": True,
                "events_verified": len(rows),
                "final_hash": expected_prev,
            }

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
            }

    def audit_stats(self) -> Dict[str, Any]:
        """Get audit trail statistics."""
        try:
            total = self.db.conn.execute("SELECT COUNT(*) FROM resonance_audit_trail").fetchone()[0]
            by_type = self.db.conn.execute(
                "SELECT event_type, COUNT(*) FROM resonance_audit_trail GROUP BY event_type ORDER BY 2 DESC"
            ).fetchall()
            by_result = self.db.conn.execute(
                "SELECT status, COUNT(*) FROM resonance_audit_trail WHERE status IS NOT NULL GROUP BY status"
            ).fetchall()
            by_actor = self.db.conn.execute(
                "SELECT actor, COUNT(*) FROM resonance_audit_trail WHERE actor IS NOT NULL GROUP BY actor ORDER BY 2 DESC LIMIT 10"
            ).fetchall()

            return {
                "total_events": total,
                "by_event_type": {r[0]: r[1] for r in by_type},
                "by_result": {r[0]: r[1] for r in by_result},
                "top_actors": {r[0]: r[1] for r in by_actor},
            }

        except Exception:
            return {}
    
    def register_sse_handler(self, handler):
        """Register a handler for SSE event streaming."""
        self._sse_handlers.append(handler)
    
    def unregister_sse_handler(self, handler):
        """Unregister an SSE handler."""
        if handler in self._sse_handlers:
            self._sse_handlers.remove(handler)
    
    # ══════════════════════════════════════════════════════════════════════════════
    # Private Methods
    # ══════════════════════════════════════════════════════════════════════════════
    
    def _persist_event(self, event: AuditEvent):
        """Store audit event to database."""
        try:
            self.db.conn.execute(
                """
                INSERT INTO resonance_audit_trail
                    (event_id, event_type, isolation_id, policy_id, actor, status, event_data, signature_hmac, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    (event.details or {}).get("isolation_id"),
                    (event.details or {}).get("policy_id"),
                    event.actor,
                    event.result,
                    json.dumps({
                        "action": event.action,
                        "resource": event.resource,
                        "details": event.details or {},
                        "hash_value": event.hash_value,
                        "prev_hash": event.prev_hash,
                    }, default=str),
                    None,
                    event.timestamp,
                ),
            )
            self.db.conn.commit()
        except Exception:
            logger.exception("resonance_audit_trail insert failed for event_id=%s", event.event_id)

    def _get_latest_hash(self) -> Optional[str]:
        """Get the hash value of the most recent audit event."""
        try:
            row = self.db.conn.execute(
                "SELECT event_data FROM resonance_audit_trail ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return json.loads(row[0]).get("hash_value")
        except Exception:
            pass
        return None

    def _compute_hash(self, event: AuditEvent) -> str:
        """
        Compute SHA3-256 hash of an event.

        Returns:
            Hex-encoded hash
        """
        canonical = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "timestamp": event.timestamp.isoformat(),
            "actor": event.actor,
            "resource": event.resource,
            "action": event.action,
            "result": event.result,
            "details": event.details,
            "prev_hash": event.prev_hash,
        }

        payload = json.dumps(canonical, sort_keys=True, default=str)
        return hashlib.sha3_256(payload.encode()).hexdigest()

    def _compute_hash_from_row(self, event: Dict[str, Any], prev_hash: str) -> str:
        """
        Recompute hash from a _row_to_event()-shaped dict for verification.
        Must mirror _compute_hash()'s canonical field set/order exactly, or
        every previously-persisted row fails verification spuriously.

        Args:
            event: dict from _row_to_event()
            prev_hash: Previous hash value

        Returns:
            Hex-encoded hash
        """
        ts = event["timestamp"]
        canonical = {
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "actor": event["actor"],
            "resource": event["resource"],
            "action": event["action"],
            "result": event["result"],
            "details": event["details"],
            "prev_hash": prev_hash,
        }

        payload = json.dumps(canonical, sort_keys=True, default=str)
        return hashlib.sha3_256(payload.encode()).hexdigest()
    
    def _emit_sse(self, event: AuditEvent):
        """Emit SSE event to all registered handlers."""
        for handler in self._sse_handlers:
            try:
                handler({
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "timestamp": event.timestamp.isoformat(),
                    "actor": event.actor,
                    "resource": event.resource,
                    "action": event.action,
                    "result": event.result,
                })
            except Exception:
                pass
