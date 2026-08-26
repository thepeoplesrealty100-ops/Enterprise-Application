"""
backend/routers/crypto.py
=========================
PQC + Encryption API router for JAKAL v2.1

Endpoints:
  POST  /crypto/pqc/sign            — Sign an action payload with ML-DSA-65
  POST  /crypto/pqc/verify          — Verify a previously signed log entry
  POST  /crypto/pqc/verify-chain    — Batch verify a chain of audit log entries
  GET   /crypto/pqc/status          — PQC module status
  GET   /crypto/pqc/audit-log       — List PQC audit log entries (from DB)

  POST  /crypto/encrypt             — AES-256-GCM encrypt a plaintext payload
  POST  /crypto/decrypt             — Decrypt a ciphertext envelope
  POST  /crypto/encrypt-report      — Encrypt a structured report dict
  GET   /crypto/status              — Encryption module status
  GET   /crypto/keys                — List registered key metadata
  POST  /crypto/keys/rotate         — Rotate a key by key_id
  POST  /crypto/keys/revoke         — Revoke a key by key_id
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel

# ── Local imports (relative; app runs from inside backend/) ────────────────
try:
    from database import DuckDBManager
    _db: Optional[DuckDBManager] = DuckDBManager()
except Exception:
    _db = None

try:
    from crypto.pqc_manager import PQCAuditManager
    from crypto.encryption_manager import EncryptionManager
    _pqc = PQCAuditManager()
    # v2.5: pass _db so session keys are persisted (KEK-wrapped) instead of
    # being regenerated from scratch — and lost — every process restart.
    # See crypto/encryption_manager.py's module docstring for the design.
    _enc = EncryptionManager(db=_db)
    CRYPTO_OK = True
except Exception as _e:
    CRYPTO_OK = False
    _CRYPTO_ERR = str(_e)

# ── Schemas ────────────────────────────────────────────────────────────────

class PQCSignRequest(BaseModel):
    agent_id: str
    operator_id: str
    action_type: str = "agent_action"
    action_payload: Dict[str, Any]

class PQCVerifyRequest(BaseModel):
    signed_log: Dict[str, Any]

class PQCChainVerifyRequest(BaseModel):
    log_entries: List[Dict[str, Any]]

class EncryptRequest(BaseModel):
    plaintext: str          # base64 or UTF-8 string payload
    use_chacha: bool = False

class DecryptRequest(BaseModel):
    envelope: Dict[str, Any]

class EncryptReportRequest(BaseModel):
    report: Dict[str, Any]
    report_id: str = ""

class KeyActionRequest(BaseModel):
    key_id: str

# ── Router ────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/crypto", tags=["crypto"])


def _require_crypto():
    if not CRYPTO_OK:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Crypto module unavailable: {_CRYPTO_ERR if not CRYPTO_OK else 'ok'}",
        )


# ══════════════════════════════════════════════════════════════════════════
# PQC endpoints
# ══════════════════════════════════════════════════════════════════════════

@router.get("/pqc/status")
def pqc_status():
    """Return PQCAuditManager status and algorithm info."""
    _require_crypto()
    return _pqc.status()


@router.post("/pqc/sign", status_code=http_status.HTTP_201_CREATED)
def pqc_sign(req: PQCSignRequest):
    """
    Sign an agent action with ML-DSA-65.
    Returns the signed log entry including pqc_signature, payload_hash, and entry_id.
    Persists entry to pqc_audit_log table if DB is available.
    """
    _require_crypto()
    signed = _pqc.sign_agent_action(
        agent_id=req.agent_id,
        action_payload=req.action_payload,
        operator_id=req.operator_id,
    )
    # Persist to DB
    if _db:
        try:
            _db.insert_pqc_audit_entry({
                "entry_id":     signed["entry_id"],
                "agent_id":     req.agent_id,
                "operator_id":  req.operator_id,
                "action_type":  req.action_type,
                "action_detail":json.dumps(req.action_payload, default=str),
                "payload_hash": signed["payload_hash"],
                "pqc_signature":signed["pqc_signature"],
                "algorithm":    signed["algorithm"],
                "public_key":   signed["public_key"],
            })
        except Exception as e:
            signed["db_persist_warning"] = str(e)
    return signed


@router.post("/pqc/verify")
def pqc_verify(req: PQCVerifyRequest):
    """Verify an ML-DSA-65 signed log entry. Returns {valid: bool}."""
    _require_crypto()
    try:
        valid = _pqc.verify_audit_log(req.signed_log)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"valid": valid, "entry_id": req.signed_log.get("entry_id")}


@router.post("/pqc/verify-chain")
def pqc_verify_chain(req: PQCChainVerifyRequest):
    """
    Batch-verify a list of signed log entries (audit chain).
    Returns per-entry verdicts and overall chain integrity.
    """
    _require_crypto()
    if not req.log_entries:
        return {"chain_valid": True, "entries_checked": 0, "failures": []}
    result = _pqc.verify_audit_chain(req.log_entries)
    return result


@router.get("/pqc/audit-log")
def list_pqc_audit_log(
    operator_id: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """List PQC-signed audit log entries from the database."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    entries = _db.list_pqc_audit_entries(
        operator_id=operator_id, action_type=action_type, limit=limit
    )
    return {"count": len(entries), "entries": entries}


# ══════════════════════════════════════════════════════════════════════════
# Encryption endpoints
# ══════════════════════════════════════════════════════════════════════════

@router.get("/status")
def encryption_status():
    """Return EncryptionManager status."""
    _require_crypto()
    return _enc.status()


@router.post("/encrypt", status_code=http_status.HTTP_201_CREATED)
def encrypt_payload(req: EncryptRequest):
    """
    Encrypt a plaintext string payload with AES-256-GCM (default) or ChaCha20-Poly1305.
    Returns the encryption envelope (does NOT contain the key — use /crypto/decrypt to recover).
    """
    _require_crypto()
    try:
        plaintext_bytes = req.plaintext.encode("utf-8")
        envelope = _enc.encrypt(plaintext_bytes, use_chacha=req.use_chacha)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return envelope


@router.post("/decrypt")
def decrypt_payload(req: DecryptRequest):
    """Decrypt an envelope returned by /crypto/encrypt. Returns {plaintext: str}."""
    _require_crypto()
    try:
        plaintext_bytes = _enc.decrypt(req.envelope)
        return {"plaintext": plaintext_bytes.decode("utf-8", errors="replace")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Decryption failed: {e}")


@router.post("/encrypt-report", status_code=http_status.HTTP_201_CREATED)
def encrypt_report(req: EncryptReportRequest):
    """
    Encrypt a structured report dict with AES-256-GCM using report_id as AAD.
    Returns the encryption envelope.
    """
    _require_crypto()
    report_id = req.report_id or str(uuid.uuid4())
    try:
        envelope = _enc.encrypt_report(req.report, report_id=report_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"report_id": report_id, **envelope}


@router.get("/public-key")
def get_public_key():
    """Export the RSA-4096 public key PEM for hybrid key exchange."""
    _require_crypto()
    return {"public_key_pem": _enc.export_public_key(), "algorithm": "RSA-4096-OAEP"}


# ── Key management ────────────────────────────────────────────────────────

@router.get("/keys")
def list_keys(
    operator_id: Optional[str] = Query(None),
    key_status: str = Query("active", alias="status"),
):
    """List encryption key metadata from the registry (never raw key bytes)."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    keys = _db.list_encryption_keys(operator_id=operator_id, status=key_status)
    return {"count": len(keys), "keys": keys}


@router.post("/keys/rotate")
def rotate_key(req: KeyActionRequest):
    """
    Rotate a key by key_id.

    v2.5: if key_id is EncryptionManager's currently active AES or ChaCha
    session key, this generates a real replacement key (used for all new
    encrypt() calls going forward) and marks the old one 'rotated' — not
    just a DB status flip on a row nothing actually reads. For a
    historical (already-rotated/unknown-to-the-session) key_id, it falls
    back to the plain DB bookkeeping flip, same as before.
    """
    _require_crypto()
    if req.key_id in (_enc._aes_key.key_id, _enc._chacha_key.key_id):
        algorithm = "ChaCha20-Poly1305" if req.key_id == _enc._chacha_key.key_id else "AES-256-GCM"
        new_key = _enc.generate_new_session_key(algorithm=algorithm)
        return {"status": "rotated", "key_id": req.key_id, "new_key": new_key}

    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    ok = _db.rotate_encryption_key(req.key_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Key {req.key_id} not found")
    return {"status": "rotated", "key_id": req.key_id}


@router.post("/keys/revoke")
def revoke_key(req: KeyActionRequest):
    """
    Immediately revoke a key by key_id — removed from active use in both
    the in-memory session store and the DB (v2.5: EncryptionManager.
    revoke_session_key() keeps both in sync; see its docstring for why
    this is deliberately more destructive than rotation).
    """
    _require_crypto()
    ok = _enc.revoke_session_key(req.key_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Key {req.key_id} not found")
    return {"status": "revoked", "key_id": req.key_id}
