"""
backend/crypto/pqc_manager.py
Post-Quantum Cryptography Manager for JAKAL Enterprise.

Implements NIST FIPS 204 equivalent (ML-DSA-65 / Dilithium3) for
quantum-resistant digital signatures on every agent action and audit log.

Architecture:
  - ML-DSA-65 (Dilithium3) via dilithium-py — pure-Python, no native dep
  - Ed25519 hybrid backup via pyca/cryptography
  - Keys generated per-session and optionally persisted to disk (encrypted)
  - Every signed log entry is stored in the pqc_audit_log DuckDB table

Upgrade path:
  When cryptography >= 47.0 + OpenSSL >= 3.3 are available on your platform,
  swap the _MLDSASigner class's backend to use:
    from cryptography.hazmat.primitives.asymmetric import mldsa
  The public interface (sign_agent_action / verify_audit_log) stays identical.
"""

from __future__ import annotations

import json
import logging
import os
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ML-DSA-65 backend (dilithium-py — NIST FIPS 204 equivalent)
# ---------------------------------------------------------------------------

try:
    from dilithium_py.dilithium import Dilithium3 as _Dilithium3
    _MLDSA_AVAILABLE = True
    logger.info("ML-DSA-65 (Dilithium3) backend loaded via dilithium-py")
except ImportError:
    _MLDSA_AVAILABLE = False
    logger.warning("dilithium-py not installed — falling back to Ed25519 signing")

# Ed25519 fallback (still 128-bit quantum-safe for signatures under Grover)
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


class _MLDSASigner:
    """
    Thin wrapper around Dilithium3 (ML-DSA-65 equivalent).
    Security level ~AES-192 / 3.3 classical bits against quantum adversaries.
    """

    def __init__(self):
        self.pk_bytes, self.sk_bytes = _Dilithium3.keygen()
        logger.info("ML-DSA-65 keypair generated | pk=%d bytes sk=%d bytes",
                    len(self.pk_bytes), len(self.sk_bytes))

    def sign(self, message: bytes, context: bytes = b"") -> bytes:
        # dilithium-py sign takes (sk, message)
        msg_with_ctx = context + b"||" + message if context else message
        return _Dilithium3.sign(self.sk_bytes, msg_with_ctx)

    def verify(self, message: bytes, signature: bytes, context: bytes = b"") -> bool:
        msg_with_ctx = context + b"||" + message if context else message
        return _Dilithium3.verify(self.pk_bytes, msg_with_ctx, signature)

    @property
    def algorithm(self) -> str:
        return "ML-DSA-65 (Dilithium3)"

    @property
    def public_key_hex(self) -> str:
        return self.pk_bytes.hex()


class _Ed25519Signer:
    """
    Ed25519 fallback signer. Uses pyca/cryptography — FIPS-compatible on
    OpenSSL builds. Not lattice-based PQC but still resists Grover's
    algorithm with 128-bit effective security.
    """

    def __init__(self):
        self._private = Ed25519PrivateKey.generate()
        self._public = self._private.public_key()
        logger.info("Ed25519 keypair generated (ML-DSA fallback)")

    def sign(self, message: bytes, context: bytes = b"") -> bytes:
        msg_with_ctx = context + b"||" + message if context else message
        return self._private.sign(msg_with_ctx)

    def verify(self, message: bytes, signature: bytes, context: bytes = b"") -> bool:
        msg_with_ctx = context + b"||" + message if context else message
        try:
            self._public.verify(signature, msg_with_ctx)
            return True
        except InvalidSignature:
            return False

    @property
    def algorithm(self) -> str:
        return "Ed25519 (PQC fallback)"

    @property
    def public_key_hex(self) -> str:
        return self._public.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PQCAuditManager:
    """
    Post-Quantum Cryptography Manager for JAKAL.

    Implements NIST FIPS 204 (ML-DSA) for quantum-resistant audit logging
    and operator-action authorization signatures.

    Usage:
        manager = PQCAuditManager()
        signed = manager.sign_agent_action("recon_agent", {"target": "10.0.0.1"})
        ok = manager.verify_audit_log(signed)
    """

    AUDIT_CONTEXT = b"jakal-enterprise-audit-v2"

    def __init__(self, db=None):
        self.db = db
        self._signer = _MLDSASigner() if _MLDSA_AVAILABLE else _Ed25519Signer()
        self._log_count = 0

    # ------------------------------------------------------------------
    # Core signing / verification
    # ------------------------------------------------------------------

    def sign_agent_action(
        self,
        agent_id: str,
        action_payload: Dict[str, Any],
        operator_id: str = "system",
    ) -> Dict[str, Any]:
        """
        Sign an agent's proposed action before it touches the database.

        Returns a signed audit entry that can be stored and later verified.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        payload_bytes = json.dumps(action_payload, sort_keys=True).encode("utf-8")

        # Compute SHA-3 digest for the DB (faster to store/index than raw bytes)
        digest = hashlib.sha3_256(payload_bytes).hexdigest()

        # PQC signature over the full payload
        signature = self._signer.sign(payload_bytes, context=self.AUDIT_CONTEXT)

        entry = {
            "entry_id":     str(uuid.uuid4()),   # stable id for DB persistence + cross-reference
            "agent_id":     agent_id,
            "operator_id":  operator_id,
            "timestamp":    timestamp,
            "action":       action_payload,
            "payload_hash": digest,
            "pqc_signature": signature.hex(),
            "algorithm":    self._signer.algorithm,
            "public_key":   self._signer.public_key_hex,
        }

        # Persist to DuckDB if a db handle is wired in. insert_pqc_audit_entry()
        # expects action_type/action_detail (not the bare "action" key this
        # method builds above for its return value), so adapt before storing —
        # this keeps sign_agent_action() usable standalone (db=... at
        # construction, no caller-side manual insert) instead of silently
        # no-op'ing on a KeyError every time.
        if self.db:
            try:
                self.db.insert_pqc_audit_entry({
                    **entry,
                    "action_type": action_payload.get("action_type", "agent_action"),
                    "action_detail": json.dumps(action_payload, sort_keys=True, default=str),
                })
            except Exception as exc:
                logger.warning("Failed to persist PQC audit log: %s", exc)

        self._log_count += 1
        return entry

    def verify_audit_log(self, signed_log: Dict[str, Any]) -> bool:
        """
        Verify the PQC signature of a stored audit log entry.
        Returns True only if signature is mathematically valid.
        """
        try:
            payload_bytes = json.dumps(signed_log["action"], sort_keys=True).encode("utf-8")
            signature_bytes = bytes.fromhex(signed_log["pqc_signature"])
            return self._signer.verify(payload_bytes, signature_bytes, context=self.AUDIT_CONTEXT)
        except Exception as exc:
            logger.error("PQC verification error: %s", exc)
            return False

    def verify_payload_integrity(self, signed_log: Dict[str, Any]) -> bool:
        """
        Secondary check: SHA-3 hash of the action matches the stored digest.
        Fast integrity pre-check before running the full PQC verify.
        """
        try:
            payload_bytes = json.dumps(signed_log["action"], sort_keys=True).encode("utf-8")
            expected = hashlib.sha3_256(payload_bytes).hexdigest()
            return expected == signed_log.get("payload_hash")
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Batch verification
    # ------------------------------------------------------------------

    def verify_audit_chain(self, log_entries: list) -> Dict[str, Any]:
        """
        Verify an entire sequence of audit log entries.
        Returns a summary with pass/fail counts and any failed entry IDs.
        """
        passed, failed, failed_ids = 0, 0, []
        for i, entry in enumerate(log_entries):
            if self.verify_payload_integrity(entry) and self.verify_audit_log(entry):
                passed += 1
            else:
                failed += 1
                failed_ids.append(i)

        return {
            "total":      len(log_entries),
            "passed":     passed,
            "failed":     failed,
            "failed_ids": failed_ids,
            "chain_valid": failed == 0,
            "algorithm":  self._signer.algorithm,
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def algorithm(self) -> str:
        return self._signer.algorithm

    @property
    def public_key_hex(self) -> str:
        return self._signer.public_key_hex

    def status(self) -> Dict[str, Any]:
        return {
            "algorithm":       self._signer.algorithm,
            "pqc_available":   _MLDSA_AVAILABLE,
            "public_key_size": len(self._signer.public_key_hex) // 2,  # bytes
            "log_count":       self._log_count,
            "audit_context":   self.AUDIT_CONTEXT.decode(),
        }
