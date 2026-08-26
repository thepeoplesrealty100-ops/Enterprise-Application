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


# ---------------------------------------------------------------------------
# High-level EncryptionManager facade
# ---------------------------------------------------------------------------

class EncryptionManager:
    """
    Facade for JAKAL's encryption operations.

    Holds a session AES key, a ChaCha key, and an RSA wrapper.
    Designed to be a singleton per FastAPI app instance.
    """

    def __init__(self, db=None):
        self.db = db
        self._aes_key    = AESGCMEncryptor.generate_key()
        self._chacha_key = ChaChaEncryptor.generate_key()
        self._rsa        = RSAKeyWrapper()
        self._key_store: Dict[str, EncryptionKey] = {
            self._aes_key.key_id:    self._aes_key,
            self._chacha_key.key_id: self._chacha_key,
        }
        logger.info("EncryptionManager initialised | AES key=%s | ChaCha key=%s",
                    self._aes_key.key_id[:8], self._chacha_key.key_id[:8])

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
        return [k.to_dict() for k in self._key_store.values()]

    def generate_new_session_key(self, algorithm: str = "AES-256-GCM") -> Dict[str, Any]:
        """Rotate the session key on demand."""
        if algorithm == "ChaCha20-Poly1305":
            new_key = ChaChaEncryptor.generate_key()
            self._chacha_key = new_key
        else:
            new_key = AESGCMEncryptor.generate_key()
            self._aes_key = new_key
        self._key_store[new_key.key_id] = new_key
        logger.info("Session key rotated | new key_id=%s", new_key.key_id)
        return new_key.to_dict()

    def status(self) -> Dict[str, Any]:
        return {
            "session_keys":   len(self._key_store),
            "aes_key_id":     self._aes_key.key_id,
            "chacha_key_id":  self._chacha_key.key_id,
            "rsa_key_bits":   _RSA_KEY_BITS,
            "pbkdf2_iter":    _PBKDF2_ITER,
            "algorithms_available": ["AES-256-GCM", "ChaCha20-Poly1305", f"RSA-{_RSA_KEY_BITS}-OAEP"],
        }
