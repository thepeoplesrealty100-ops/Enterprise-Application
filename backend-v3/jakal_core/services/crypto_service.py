"""Crypto service: PQC-signed audit log + encryption-key lifecycle (/api/crypto/).

Resolves three teardown findings at once:
  * GAP-05  hybrid ML-DSA-65 + Ed25519 signing, algorithm recorded per row.
  * GAP-03  rotate/revoke return real affected-row semantics (raise NotFound
            instead of silently returning False on a live key).
  * GAP-07  data keys are stored only envelope-wrapped; rotation keeps the old
            key decryptable and records a rotation-history row.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto.envelope import new_data_key, unwrap_key, wrap_key
from ..crypto.pqc import HybridSigner, SignatureBundle
from ..errors import CryptoPolicyError, NotFoundError
from ..logging_config import get_logger
from ..models import EncryptionKey, KeyRotationHistory, KeyStatus, PQCAuditEntry

logger = get_logger(__name__)


class CryptoService:
    def __init__(self, session: AsyncSession, signer: HybridSigner, master_key: str) -> None:
        self._s = session
        self._signer = signer
        self._master_key = master_key

    # ── Audit signing (/api/crypto/sign, verify) ───────────────────────────
    async def sign_agent_action(
        self, agent_id: str, action_payload: dict, operator_id: str
    ) -> PQCAuditEntry:
        payload_bytes = json.dumps(action_payload, sort_keys=True, default=str).encode()
        digest = hashlib.sha3_256(payload_bytes).hexdigest()
        bundle: SignatureBundle = self._signer.sign(payload_bytes)

        entry = PQCAuditEntry(
            entry_id=uuid.uuid4(),
            agent_id=agent_id,
            operator_id=operator_id,
            action_type=str(action_payload.get("action_type", "agent_action")),
            action_detail=json.dumps(action_payload, sort_keys=True, default=str),
            payload_hash=digest,
            algorithm=bundle.algorithm,
            pqc_signature=bundle.pqc_signature or "",
            classical_signature=bundle.classical_signature,
            public_key=bundle.public_key or "",
            classical_public_key=bundle.classical_public_key,
        )
        self._s.add(entry)
        await self._s.flush()
        logger.info(
            "pqc audit signed",
            extra={"extra": {"entry_id": str(entry.entry_id), "algorithm": bundle.algorithm}},
        )
        return entry

    async def verify_entry(self, entry_id: uuid.UUID, *, require_pqc: bool | None = None) -> bool:
        entry = await self._s.get(PQCAuditEntry, entry_id)
        if entry is None:
            raise NotFoundError(f"audit entry {entry_id} not found")
        bundle = SignatureBundle(
            algorithm=entry.algorithm,
            pqc_signature=entry.pqc_signature or None,
            classical_signature=entry.classical_signature,
            public_key=entry.public_key or None,
            classical_public_key=entry.classical_public_key or "",
        )
        message = entry.action_detail.encode()
        ok = self._signer.verify(message, bundle, require_pqc=require_pqc)
        if require_pqc and not entry.pqc_signature:
            raise CryptoPolicyError(
                f"entry {entry_id} was signed {entry.algorithm} but PQC is required"
            )
        return ok

    # ── Key lifecycle (/api/crypto/keys) ────────────────────────────────────
    async def register_key(
        self, algorithm: str = "AES-256-GCM", purpose: str = "data-at-rest", metadata: dict | None = None
    ) -> EncryptionKey:
        """Mint a data key, wrap it under the KEK, and persist. This is the path
        the reviewed code declared but never called — so ``encryption_keys``
        stayed empty. It is wired here."""
        data_key = new_data_key()
        wrapped, nonce = wrap_key(data_key, self._master_key)
        key = EncryptionKey(
            key_id=uuid.uuid4(),
            algorithm=algorithm,
            purpose=purpose,
            status=KeyStatus.ACTIVE,
            wrapped_key=wrapped,
            wrap_nonce=nonce,
            key_metadata=metadata or {},
        )
        self._s.add(key)
        await self._s.flush()
        return key

    async def get_data_key(self, key_id: uuid.UUID) -> bytes:
        key = await self._s.get(EncryptionKey, key_id)
        if key is None:
            raise NotFoundError(f"key {key_id} not found")
        if key.status is KeyStatus.REVOKED:
            raise CryptoPolicyError(f"key {key_id} is revoked and cannot be used")
        return unwrap_key(key.wrapped_key, key.wrap_nonce, self._master_key)

    async def rotate_key(self, key_id: uuid.UUID, rotated_by: str, reason: str = "") -> EncryptionKey:
        """Rotate: mint a replacement, mark the old key ``rotated`` (still
        decryptable for data encrypted under it), record history, return the
        NEW key. Raises NotFound on a missing/already-retired key — no silent
        False (GAP-03)."""
        old = await self._s.get(EncryptionKey, key_id)
        if old is None:
            raise NotFoundError(f"key {key_id} not found")
        if old.status is not KeyStatus.ACTIVE:
            raise CryptoPolicyError(f"only an ACTIVE key can be rotated (key is {old.status.value})")

        new_key = await self.register_key(algorithm=old.algorithm, purpose=old.purpose)
        old.status = KeyStatus.ROTATED
        old.retired_at = datetime.now(UTC)
        self._s.add(
            KeyRotationHistory(
                rotation_id=uuid.uuid4(),
                old_key_id=old.key_id,
                new_key_id=new_key.key_id,
                reason=reason,
                rotated_by=rotated_by,
            )
        )
        await self._s.flush()
        logger.info(
            "key rotated",
            extra={"extra": {"old": str(old.key_id), "new": str(new_key.key_id), "by": rotated_by}},
        )
        return new_key

    async def revoke_key(self, key_id: uuid.UUID, revoked_by: str, reason: str = "") -> EncryptionKey:
        """Revoke: the key can no longer decrypt. Raises NotFound if absent."""
        key = await self._s.get(EncryptionKey, key_id)
        if key is None:
            raise NotFoundError(f"key {key_id} not found")
        key.status = KeyStatus.REVOKED
        key.retired_at = datetime.now(UTC)
        self._s.add(
            KeyRotationHistory(
                rotation_id=uuid.uuid4(),
                old_key_id=key.key_id,
                new_key_id=None,
                reason=reason or "revoked",
                rotated_by=revoked_by,
            )
        )
        await self._s.flush()
        return key

    async def list_keys(self, status: KeyStatus | None = None) -> list[EncryptionKey]:
        """List keys, optionally filtered. ``status=None`` returns all lifecycle
        states (the reviewed code's requested behaviour)."""
        stmt = select(EncryptionKey).order_by(EncryptionKey.created_at.desc())
        if status is not None:
            stmt = stmt.where(EncryptionKey.status == status)
        return list((await self._s.execute(stmt)).scalars().all())
