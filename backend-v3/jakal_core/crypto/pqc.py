"""Hybrid post-quantum signing (GAP-05).

Signs every audit payload with BOTH:

  * ML-DSA-65 (FIPS 204, via dilithium-py) — the quantum-resistant signature.
  * Ed25519 (pyca/cryptography) — a fast classical signature.

Why hybrid: during the PQC migration window (NIST SP 1800-38) neither the
lattice scheme nor the classical scheme is universally trusted in isolation, so
a verifier can require BOTH to pass. The algorithm string is emitted with every
signature and persisted per-row, so a later algorithm rollover never orphans
old data.

The teardown's finding was that the old code silently downgraded to Ed25519
when dilithium-py was missing, invalidating the PQC claim without telling
anyone. Here, ``strict`` mode makes PQC availability a hard requirement: a
signer constructed with ``strict=True`` on a host without the ML-DSA backend
raises immediately rather than producing a weaker signature that looks the same.
"""
from __future__ import annotations

from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

try:
    from dilithium_py.ml_dsa import ML_DSA_65

    MLDSA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only on hosts without the lib
    ML_DSA_65 = None  # type: ignore[assignment]
    MLDSA_AVAILABLE = False


ALGO_HYBRID = "ML-DSA-65+Ed25519"
ALGO_CLASSICAL_ONLY = "Ed25519"
_CTX = b"jakal-enterprise-audit-v3"


class CryptoUnavailableError(RuntimeError):
    """Raised when strict mode requires the PQC backend and it is absent."""


@dataclass(frozen=True)
class SignatureBundle:
    algorithm: str
    pqc_signature: str | None            # hex, ML-DSA-65
    classical_signature: str             # hex, Ed25519
    public_key: str | None               # hex, ML-DSA-65 pk
    classical_public_key: str            # hex, Ed25519 pk


class HybridSigner:
    """Owns one keypair pair for the process lifetime.

    In production the private keys would be loaded from KMS/HSM rather than
    generated per process; the public interface is identical either way.
    """

    def __init__(self, strict: bool = False) -> None:
        self._strict = strict
        if strict and not MLDSA_AVAILABLE:
            raise CryptoUnavailableError(
                "crypto_strict is set but the ML-DSA-65 backend (dilithium-py) "
                "is not installed — refusing to start with a downgraded signer."
            )
        self._use_pqc = MLDSA_AVAILABLE
        if self._use_pqc:
            self._mldsa_pk, self._mldsa_sk = ML_DSA_65.keygen()
        else:  # pragma: no cover
            self._mldsa_pk = self._mldsa_sk = None
        self._ed_sk = Ed25519PrivateKey.generate()
        self._ed_pk = self._ed_sk.public_key()

    # ── public key material ────────────────────────────────────────────────
    @property
    def algorithm(self) -> str:
        return ALGO_HYBRID if self._use_pqc else ALGO_CLASSICAL_ONLY

    @property
    def pqc_available(self) -> bool:
        return self._use_pqc

    def _ed_pk_hex(self) -> str:
        return self._ed_pk.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()

    # ── sign / verify ──────────────────────────────────────────────────────
    def sign(self, message: bytes) -> SignatureBundle:
        classical = self._ed_sk.sign(message).hex()
        if self._use_pqc:
            pqc = ML_DSA_65.sign(self._mldsa_sk, message, ctx=_CTX).hex()
            return SignatureBundle(
                algorithm=ALGO_HYBRID,
                pqc_signature=pqc,
                classical_signature=classical,
                public_key=self._mldsa_pk.hex(),
                classical_public_key=self._ed_pk_hex(),
            )
        return SignatureBundle(
            algorithm=ALGO_CLASSICAL_ONLY,
            pqc_signature=None,
            classical_signature=classical,
            public_key=None,
            classical_public_key=self._ed_pk_hex(),
        )

    def verify(self, message: bytes, bundle: SignatureBundle, *, require_pqc: bool | None = None) -> bool:
        """Verify a bundle produced by ``sign``.

        ``require_pqc`` defaults to the signer's own strict flag: when True,
        a bundle without a valid ML-DSA signature fails even if the classical
        signature is fine — this is what makes the PQC guarantee real.
        """
        require_pqc = self._strict if require_pqc is None else require_pqc

        # Classical leg
        try:
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(bundle.classical_public_key)
            ).verify(bytes.fromhex(bundle.classical_signature), message)
            classical_ok = True
        except (InvalidSignature, ValueError):
            classical_ok = False

        # PQC leg
        if bundle.pqc_signature and bundle.public_key and MLDSA_AVAILABLE:
            pqc_ok = ML_DSA_65.verify(
                bytes.fromhex(bundle.public_key),
                message,
                bytes.fromhex(bundle.pqc_signature),
                ctx=_CTX,
            )
        else:
            pqc_ok = False

        if require_pqc:
            return classical_ok and pqc_ok
        # Non-strict: classical must hold; PQC strengthens but is not mandatory.
        return classical_ok
