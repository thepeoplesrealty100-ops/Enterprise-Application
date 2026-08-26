"""
backend/crypto/encryption_manager.py
Enterprise Encryption Manager for JAKAL.

Provides:
  - AES-256-GCM  — authenticated symmetric encryption for data at rest / transit
  - RSA-4096-OAEP — asymmetric key wrapping for hybrid schemes
  - ChaCha20-Poly1305 — high-speed AEAD for streaming data
  - Hybrid encryption — RSA-wrapped AES key + AES-GCM ciphertext (envelopes)
  - Key derivation — PBKDF2-SHA3 + HKDF for session keys

All operations use pyca/cryptography (the gold-standard Python crypto library)
and are appropriate for securing:
  - Pentest report storage at rest
  - Operator-to-operator secure message channels
  - Evidence packages submitted to clients
  - DuckDB snapshot encryption
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)

# Nonce / salt sizes (bytes)
_AES_GCM_NONCE  = 12   # 96-bit — NIST recommended for GCM
_CHACHA_NONCE   = 12   # 96-bit
_PBKDF2_ITER    = 600_000  # OWASP 2024 minimum for PBKDF2-SHA256
_RSA_KEY_BITS   = 4096

# ---------------------------------------------------------------------------
# Key persistence — KEK/DEK envelope wrapping (v2.5)
# ---------------------------------------------------------------------------
# Found while wiring up JAKAL v2.5: EncryptionManager generated a fresh AES
# and ChaCha key in memory on every process start and NEVER persisted them
# anywhere -- so every report encrypted with encrypt_report() became
# permanently unreadable the moment the process restarted. Separately,
# database.py's encryption_keys table (register/rotate/revoke/list) had no
# callers anywhere in the app -- a second, disconnected, always-empty key
# inventory that GET/POST /crypto/keys operated on for nothing.
#
# The fix: session keys (DEKs) ARE now persisted to encryption_keys, but
# never in the clear -- each one is wrapped with a Key-Encryption-Key (KEK)
# derived via HKDF (derive_session_key(), below, already existed and had no
# callers either) from a JAKAL_MASTER_KEY secret that lives only in the
# environment, never in the database. This is the standard KEK/DEK envelope
# pattern: compromising the DuckDB file alone doesn't recover any key
# material without also having the master secret.
#
# The encryption_keys table's own column comment says wrapped_key holds a
# key "wrapped with RSA-OAEP" -- this deliberately does NOT do that, even
# though RSAKeyWrapper already exists below. RSA-wrapping only moves the
# problem: EncryptionManager's RSA keypair is *also* generated fresh every
# process start, so wrapping a DEK with it doesn't survive a restart either
# unless the RSA private key itself is made durable -- which reintroduces
# exactly the same "where does the root secret live" question one level up,
# with more moving parts (PEM handling, no expiry story) for no extra
# safety over a single symmetric KEK from the environment. If a real KMS
# (AWS KMS, HashiCorp Vault, etc.) is available in a given deployment, that
# is the correct place to hold the root secret instead of an env var --
# swapping _resolve_kek()'s source is the intended extension point.
_MASTER_KEY_ENV = "JAKAL_MASTER_KEY"


# ---------------------------------------------------------------------------
# Key management dataclass
# ---------------------------------------------------------------------------

@dataclass
class EncryptionKey:
    key_id:     str
    algorithm:  str
    key_bytes:  bytes
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    label:      str = ""

    def to_dict(self) -> dict:
        """Serialisable summary — key_bytes is NOT included."""
        return {
            "key_id":     self.key_id,
            "algorithm":  self.algorithm,
            "key_size":   len(self.key_bytes) * 8,
            "created_at": self.created_at,
            "label":      self.label,
        }


# ---------------------------------------------------------------------------
# AES-256-GCM
# ---------------------------------------------------------------------------

class AESGCMEncryptor:
    """Authenticated encryption with AES-256-GCM."""

    @staticmethod
    def generate_key() -> EncryptionKey:
        import uuid
        key_bytes = os.urandom(32)  # 256 bits
        return EncryptionKey(
            key_id=str(uuid.uuid4()),
            algorithm="AES-256-GCM",
            key_bytes=key_bytes,
        )

    @staticmethod
    def encrypt(
        key: EncryptionKey,
        plaintext: bytes,
        associated_data: Optional[bytes] = None,
    ) -> Dict[str, str]:
        """
        Encrypt plaintext with AES-256-GCM.
        Returns a JSON-safe dict with base64-encoded nonce + ciphertext + aad.
        """
        nonce = os.urandom(_AES_GCM_NONCE)
        aesgcm = AESGCM(key.key_bytes)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)
        return {
            "algorithm":        "AES-256-GCM",
            "key_id":           key.key_id,
            "nonce_b64":        base64.b64encode(nonce).decode(),
            "ciphertext_b64":   base64.b64encode(ciphertext).decode(),
            "aad_b64":          base64.b64encode(associated_data).decode() if associated_data else None,
        }

    @staticmethod
    def decrypt(key: EncryptionKey, envelope: Dict[str, str]) -> bytes:
        """Decrypt and verify an AES-256-GCM envelope. Raises InvalidTag on tamper."""
        nonce      = base64.b64decode(envelope["nonce_b64"])
        ciphertext = base64.b64decode(envelope["ciphertext_b64"])
        aad        = base64.b64decode(envelope["aad_b64"]) if envelope.get("aad_b64") else None
        aesgcm = AESGCM(key.key_bytes)
        return aesgcm.decrypt(nonce, ciphertext, aad)


# ---------------------------------------------------------------------------
# ChaCha20-Poly1305  (preferred for high-throughput / streaming paths)
# ---------------------------------------------------------------------------

class ChaChaEncryptor:
    """ChaCha20-Poly1305 AEAD — faster than AES on CPUs without AES-NI."""

    @staticmethod
    def generate_key() -> EncryptionKey:
        import uuid
        return EncryptionKey(
            key_id=str(uuid.uuid4()),
            algorithm="ChaCha20-Poly1305",
            key_bytes=os.urandom(32),
        )

    @staticmethod
    def encrypt(key: EncryptionKey, plaintext: bytes, aad: Optional[bytes] = None) -> Dict[str, str]:
        nonce = os.urandom(_CHACHA_NONCE)
        chacha = ChaCha20Poly1305(key.key_bytes)
        ct = chacha.encrypt(nonce, plaintext, aad)
        return {
            "algorithm":      "ChaCha20-Poly1305",
            "key_id":         key.key_id,
            "nonce_b64":      base64.b64encode(nonce).decode(),
            "ciphertext_b64": base64.b64encode(ct).decode(),
            "aad_b64":        base64.b64encode(aad).decode() if aad else None,
        }

    @staticmethod
    def decrypt(key: EncryptionKey, envelope: Dict[str, str]) -> bytes:
        nonce = base64.b64decode(envelope["nonce_b64"])
        ct    = base64.b64decode(envelope["ciphertext_b64"])
        aad   = base64.b64decode(envelope["aad_b64"]) if envelope.get("aad_b64") else None
        return ChaCha20Poly1305(key.key_bytes).decrypt(nonce, ct, aad)


# ---------------------------------------------------------------------------
# RSA-4096-OAEP  (key wrapping only — don't use RSA to encrypt bulk data)
# ---------------------------------------------------------------------------

class RSAKeyWrapper:
    """RSA-4096-OAEP for wrapping symmetric keys (envelope encryption)."""

    def __init__(self):
        self._private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=_RSA_KEY_BITS,
            backend=default_backend(),
        )
        self._public = self._private.public_key()
        logger.info("RSA-%d keypair generated", _RSA_KEY_BITS)

    def wrap_key(self, sym_key: EncryptionKey) -> str:
        """Wrap a symmetric key with RSA-OAEP. Returns base64 ciphertext."""
        ct = self._public.encrypt(
            sym_key.key_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(ct).decode()

    def unwrap_key(self, wrapped_b64: str, algorithm: str, key_id: str, label: str = "") -> EncryptionKey:
        """Unwrap a symmetric key encrypted with our public key."""
        ct = base64.b64decode(wrapped_b64)
        key_bytes = self._private.decrypt(
            ct,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return EncryptionKey(key_id=key_id, algorithm=algorithm, key_bytes=key_bytes, label=label)

    def export_public_key_pem(self) -> str:
        return self._public.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()


# ---------------------------------------------------------------------------
# Key Derivation
# ---------------------------------------------------------------------------

def derive_key_from_password(password: str, salt: Optional[bytes] = None) -> Tuple[EncryptionKey, bytes]:
    """
    Derive an AES-256 key from a password using PBKDF2-SHA256.
    Returns (EncryptionKey, salt) — store the salt alongside the ciphertext.
    """
    import uuid
    if salt is None:
        salt = os.urandom(32)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITER,
        backend=default_backend(),
    )
    key_bytes = kdf.derive(password.encode())
    key = EncryptionKey(
        key_id=str(uuid.uuid4()),
        algorithm="AES-256-GCM (PBKDF2)",
        key_bytes=key_bytes,
    )
    return key, salt


def derive_session_key(master_secret: bytes, info: bytes = b"jakal-session") -> EncryptionKey:
    """Derive a per-session AES-256 key from a master secret using HKDF-SHA256."""
    import uuid
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=info,
        backend=default_backend(),
    )
    return EncryptionKey(
        key_id=str(uuid.uuid4()),
        algorithm="AES-256-GCM (HKDF)",
        key_bytes=hkdf.derive(master_secret),
    )


def _resolve_kek() -> Tuple[bytes, bool]:
    """
    Returns (kek_bytes, from_persistent_source). When JAKAL_MASTER_KEY is
    set in the environment, the KEK is deterministically derived from it
    (HKDF-SHA256), so it's the same key across restarts -- persisted DEKs
    stay unwrappable. When it isn't set, a random master is generated for
    this process only: the app still works, but anything persisted this
    run becomes unrecoverable the moment the process exits. Callers should
    warn loudly in that case rather than fail startup -- same "insecure but
    functional default, please configure for production" pattern already
    used for CLAUDE_API_KEY elsewhere in this app.
    """
    raw = os.environ.get(_MASTER_KEY_ENV, "")
    if raw:
        master, persistent = raw.encode("utf-8"), True
    else:
        master, persistent = os.urandom(32), False
    kek = derive_session_key(master, info=b"jakal-kek-v1").key_bytes
    return kek, persistent


def _wrap_key_bytes(kek: bytes, raw: bytes) -> str:
    """AES-256-GCM-encrypt raw DEK bytes under the KEK. Returns a JSON
    string (nonce + ciphertext, base64) safe to store in a VARCHAR column."""
    nonce = os.urandom(_AES_GCM_NONCE)
    ct = AESGCM(kek).encrypt(nonce, raw, None)
    return json.dumps({
        "nonce_b64": base64.b64encode(nonce).decode(),
        "ct_b64": base64.b64encode(ct).decode(),
    })


def _unwrap_key_bytes(kek: bytes, wrapped_json: str) -> bytes:
    """Inverse of _wrap_key_bytes(). Raises on tamper or a KEK mismatch
    (e.g. JAKAL_MASTER_KEY changed since this key was wrapped)."""
    obj = json.loads(wrapped_json)
    nonce = base64.b64decode(obj["nonce_b64"])
    ct = base64.b64decode(obj["ct_b64"])
    return AESGCM(kek).decrypt(nonce, ct, None)


# ---------------------------------------------------------------------------
# High-level EncryptionManager facade
# ---------------------------------------------------------------------------

class EncryptionManager:
    """
    Facade for JAKAL's encryption operations.

    Holds a session AES key, a ChaCha key, and an RSA wrapper.
    Designed to be a singleton per FastAPI app instance.

    v2.5: when constructed with a `db` (as routers/crypto.py now does),
    session keys are persisted -- KEK-wrapped, never in the clear -- to
    encryption_keys, and rehydrated from there on the next startup instead
    of being regenerated from scratch every time. Without a db (e.g. the
    standalone `EncryptionManager()` usage in tests/test_20x_validation.py)
    it behaves exactly as before: fresh in-memory-only keys each run.
    """

    def __init__(self, db=None, operator_id: str = "system"):
        self.db = db
        self.operator_id = operator_id
        self._kek, self._kek_persistent = _resolve_kek()
        if not self._kek_persistent:
            logger.warning(
                "%s not set -- using an ephemeral master key for this process. "
                "Session keys will still be recorded in encryption_keys, but "
                "they will NOT be recoverable after a restart (the key wrapping "
                "them is gone). Set %s in backend/.env for production use.",
                _MASTER_KEY_ENV, _MASTER_KEY_ENV,
            )

        self._key_store: Dict[str, EncryptionKey] = {}
        self._rsa = RSAKeyWrapper()

        self._aes_key    = self._load_or_create_key("AES-256-GCM")
        self._chacha_key = self._load_or_create_key("ChaCha20-Poly1305")

        logger.info("EncryptionManager initialised | AES key=%s | ChaCha key=%s | persistence=%s",
                    self._aes_key.key_id[:8], self._chacha_key.key_id[:8],
                    "db-backed" if self.db else "in-memory-only")

    # ------------------------------------------------------------------
    # Key persistence (v2.5)
    # ------------------------------------------------------------------

    def _load_or_create_key(self, algorithm: str) -> EncryptionKey:
        """Rehydrate the most recently active key of this algorithm from
        encryption_keys (unwrapping with the KEK), or generate + persist a
        fresh one if none exists or none can be unwrapped."""
        if self.db:
            try:
                for row in self.db.list_encryption_key_material(status="active"):
                    if row["algorithm"] != algorithm or not row.get("wrapped_key"):
                        continue
                    try:
                        raw = _unwrap_key_bytes(self._kek, row["wrapped_key"])
                    except Exception:
                        continue  # wrong/rotated KEK -- unrecoverable, try the next row
                    key = EncryptionKey(key_id=row["key_id"], algorithm=algorithm, key_bytes=raw)
                    self._key_store[key.key_id] = key
                    return key
            except Exception as e:
                logger.warning("Could not rehydrate %s key from encryption_keys: %s", algorithm, e)

        new_key = (ChaChaEncryptor if algorithm == "ChaCha20-Poly1305" else AESGCMEncryptor).generate_key()
        self._key_store[new_key.key_id] = new_key
        self._persist_key(new_key)
        return new_key

    def _persist_key(self, key: EncryptionKey) -> None:
        if not self.db:
            return
        try:
            self.db.register_encryption_key({
                "key_id": key.key_id, "algorithm": key.algorithm,
                "key_purpose": "session", "operator_id": self.operator_id,
                "key_wrapping_algo": "AES-256-GCM-KEK(HKDF)",
                "wrapped_key": _wrap_key_bytes(self._kek, key.key_bytes),
            })
        except Exception as e:
            logger.warning("Could not persist encryption key %s: %s", key.key_id, e)

    # ------------------------------------------------------------------
    # Session encryption  (use these for most operations)
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: str | bytes, use_chacha: bool = False) -> Dict[str, Any]:
        """Encrypt data with the session key. Returns a portable envelope dict."""
        data = plaintext.encode() if isinstance(plaintext, str) else plaintext
        if use_chacha:
            return ChaChaEncryptor.encrypt(self._chacha_key, data)
        return AESGCMEncryptor.encrypt(self._aes_key, data)

    def decrypt(self, envelope: Dict[str, Any]) -> bytes:
        """Decrypt an envelope. Key is looked up by key_id inside the envelope."""
        key_id = envelope.get("key_id")
        key = self._key_store.get(key_id)
        if key is None:
            raise KeyError(f"Key {key_id!r} not in session store")
        algo = envelope.get("algorithm", "")
        if "ChaCha" in algo:
            return ChaChaEncryptor.decrypt(key, envelope)
        return AESGCMEncryptor.decrypt(key, envelope)

    # ------------------------------------------------------------------
    # Report / evidence encryption
    # ------------------------------------------------------------------

    def encrypt_report(self, report: Dict[str, Any], report_id: str) -> Dict[str, Any]:
        """
        Encrypt a pentest report for secure storage.
        Uses AES-256-GCM with the report_id as associated data (prevents swap attacks).
        """
        plaintext = json.dumps(report, default=str).encode()
        envelope = AESGCMEncryptor.encrypt(
            self._aes_key,
            plaintext,
            associated_data=report_id.encode(),
        )
        envelope["report_id"] = report_id
        envelope["encrypted_at"] = datetime.now(timezone.utc).isoformat()
        return envelope

    def decrypt_report(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        report_id = envelope.get("report_id", "")
        key = self._key_store.get(envelope["key_id"])
        if key is None:
            raise KeyError("Report encryption key not in session store")
        raw = AESGCMEncryptor.decrypt(key, {**envelope, "aad_b64": base64.b64encode(report_id.encode()).decode()})
        return json.loads(raw)

    # ------------------------------------------------------------------
    # Key export / status
    # ------------------------------------------------------------------

    def export_public_key(self) -> str:
        """RSA public key PEM — share with operators for key-wrapping workflows."""
        return self._rsa.export_public_key_pem()

    def list_keys(self) -> list:
        """
        Prefers the persisted, authoritative inventory (encryption_keys,
        every lifecycle state) when a db is wired -- this is what makes
        GET /crypto/keys finally show real data instead of always being
        empty. Falls back to the in-memory store's metadata when there's
        no db (standalone usage) or the query fails.
        """
        if self.db:
            try:
                return self.db.list_encryption_keys(status=None)
            except Exception as e:
                logger.warning("Falling back to in-memory key list: %s", e)
        return [k.to_dict() for k in self._key_store.values()]

    def generate_new_session_key(self, algorithm: str = "AES-256-GCM") -> Dict[str, Any]:
        """
        Rotate the session key on demand. The old key stays in the
        in-memory store (and, if persisted, its DB row moves to 'rotated'
        rather than being deleted) so anything already encrypted under it
        stays decryptable -- only NEW encrypt() calls use the new key.
        """
        if algorithm == "ChaCha20-Poly1305":
            old_key, new_key = self._chacha_key, ChaChaEncryptor.generate_key()
            self._chacha_key = new_key
        else:
            old_key, new_key = self._aes_key, AESGCMEncryptor.generate_key()
            self._aes_key = new_key
        self._key_store[new_key.key_id] = new_key
        self._persist_key(new_key)
        if self.db:
            try:
                self.db.rotate_encryption_key(old_key.key_id)
            except Exception as e:
                logger.warning("Could not mark old key %s as rotated: %s", old_key.key_id, e)
        logger.info("Session key rotated | new key_id=%s", new_key.key_id)
        return new_key.to_dict()

    def revoke_session_key(self, key_id: str) -> bool:
        """
        Revoke a key -- unlike rotation, this makes it permanently unusable:
        removed from the in-memory store so decrypt() can no longer find it
        (anything still encrypted under it becomes unreadable -- that's the
        point, for a suspected-compromised key rather than routine
        rotation), and marked 'revoked' in the DB. If the revoked key was
        currently active, a replacement is generated immediately so
        encrypt() keeps working.
        """
        existed_in_memory = self._key_store.pop(key_id, None) is not None

        if key_id == getattr(self._aes_key, "key_id", None):
            self._aes_key = AESGCMEncryptor.generate_key()
            self._key_store[self._aes_key.key_id] = self._aes_key
            self._persist_key(self._aes_key)
        if key_id == getattr(self._chacha_key, "key_id", None):
            self._chacha_key = ChaChaEncryptor.generate_key()
            self._key_store[self._chacha_key.key_id] = self._chacha_key
            self._persist_key(self._chacha_key)

        existed_in_db = False
        if self.db:
            try:
                existed_in_db = self.db.revoke_encryption_key(key_id)
            except Exception as e:
                logger.warning("Could not mark key %s as revoked: %s", key_id, e)

        return existed_in_memory or existed_in_db

    def status(self) -> Dict[str, Any]:
        return {
            "session_keys":   len(self._key_store),
            "aes_key_id":     self._aes_key.key_id,
            "chacha_key_id":  self._chacha_key.key_id,
            "rsa_key_bits":   _RSA_KEY_BITS,
            "pbkdf2_iter":    _PBKDF2_ITER,
            "algorithms_available": ["AES-256-GCM", "ChaCha20-Poly1305", f"RSA-{_RSA_KEY_BITS}-OAEP"],
            "key_persistence": "db-backed" if self.db else "in-memory-only",
            "kek_source": ("JAKAL_MASTER_KEY env var" if self._kek_persistent
                            else "ephemeral (set JAKAL_MASTER_KEY for durability across restarts)"),
        }
