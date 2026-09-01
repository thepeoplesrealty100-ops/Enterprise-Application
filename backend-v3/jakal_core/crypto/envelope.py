"""Envelope encryption for the key lifecycle (GAP-07).

Data keys are never stored in the clear. Each is wrapped (AES-256-GCM) under a
Key-Encryption-Key derived from the configured master key. In production the
master key comes from a KMS/HSM and this module wraps/unwraps via the KMS API;
here it derives a local KEK so the lifecycle is exercisable end-to-end.
"""
from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _derive_kek(master_key: str) -> bytes:
    if not master_key:
        raise ValueError("master key is empty — refusing to wrap with a null KEK")
    # HKDF-lite: a domain-separated SHA-256 of the master secret → 256-bit KEK.
    return hashlib.sha256(b"jakal-kek-v3|" + master_key.encode()).digest()


def wrap_key(data_key: bytes, master_key: str) -> tuple[bytes, bytes]:
    """Return (wrapped_key, nonce)."""
    kek = _derive_kek(master_key)
    nonce = os.urandom(12)
    wrapped = AESGCM(kek).encrypt(nonce, data_key, b"jakal-data-key")
    return wrapped, nonce


def unwrap_key(wrapped_key: bytes, nonce: bytes, master_key: str) -> bytes:
    kek = _derive_kek(master_key)
    return AESGCM(kek).decrypt(nonce, wrapped_key, b"jakal-data-key")


def new_data_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)
