# Crypto-Agility & CNSA 2.0 Readiness

## Current profile: commercial (ML-DSA-65)

Every PQC signature JAKAL produces today — every staged/approved/denied
payload, every Maya-Vigesimal challenge creation and consumption, every
crypto/vault/audit operation — is signed with **ML-DSA-65** (NIST FIPS
204, via the `Dilithium3` parameter set in `dilithium-py`). This is the
correct default for general commercial/enterprise use: NIST FIPS 204
designates ML-DSA-65 as its baseline general-purpose signature parameter
set, appropriate security margin without CNSA 2.0's stricter (and
heavier) requirements.

No module outside `backend/crypto/pqc_manager.py` hardcodes "65",
"Dilithium3", or any other parameter-set-specific string as an
assumption. Code that needs to know what algorithm is in play reads it
back from `PQCAuditManager.algorithm` / `.profile` / `.status()` at
runtime instead.

## The system is deliberately crypto-agile

`backend/crypto/pqc_manager.py` selects its signer from a small registry:

```python
PQC_PARAMETER_SETS = {
    "commercial": {"dilithium_cls": "Dilithium3", "label": "ML-DSA-65"},
    "cnsa2":      {"dilithium_cls": "Dilithium5", "label": "ML-DSA-87"},
}
```

Which entry is used is controlled by a config flag:

```python
PQC_PROFILE = "commercial"   # default -> ML-DSA-65
# "cnsa2" -> ML-DSA-87
```

exposed as `Config.PQC_PROFILE` (`backend/config/__init__.py`), driven by
the `PQC_PROFILE` environment variable, and read by every
`PQCAuditManager()` construction site by default. Every existing call
site in this codebase constructs `PQCAuditManager()` with no arguments
and therefore keeps signing with ML-DSA-65 — the profile is opt-in per
instance (`PQCAuditManager(profile="cnsa2")`), not a global behavior
change.

## Path to CNSA 2.0 (ML-DSA-87 + ML-KEM-1024)

[CNSA 2.0](https://media.defense.gov/2022/Sep/07/2003071834/-1/-1/0/CSA_CNSA_2.0_ALGORITHMS_.PDF)
(NSA's Commercial National Security Algorithm Suite 2.0) is the algorithm
suite required for **National Security Systems**. NSA's published
timeline calls for new acquisitions to require it by roughly 2027, and
for full transition across fielded NSS by roughly 2030–2031. JAKAL is not
an NSS product today, so forcing CNSA 2.0 now would add signature/key
weight for no benefit to a commercial deployment — but the path is ready
whenever a customer or regulatory requirement needs it:

- **Signatures**: switching `PQC_PROFILE` to `"cnsa2"` moves every new
  signature to **ML-DSA-87** (`Dilithium5`) instead of ML-DSA-65. This is
  not a stub — `dilithium-py` already ships `Dilithium5` cleanly, and it
  is exercised end-to-end (keygen/sign/verify) by
  `backend/tests/test_crypto_agility.py`. Switching profiles is a
  **configuration change + key regeneration** (existing ML-DSA-65 keys
  and already-signed audit entries stay valid and verifiable under their
  original algorithm — nothing is retroactively re-signed), not a
  rewrite of any calling code.
- **Key exchange**: CNSA 2.0 also requires **ML-KEM-1024** for key
  establishment. JAKAL does not currently perform PQC key exchange — its
  PQC usage is pure signing (audit non-repudiation), where hybrid
  classical+PQC is not the relevant concern; hybrid schemes matter mainly
  for key exchange, which this system is not forcing yet. ML-KEM-1024 is
  intentionally **not implemented** in this phase — it is a distinct
  primitive (key encapsulation, not signing) with no existing call site
  in this codebase to retrofit, and adding one speculatively would be new
  functionality this phase's scope explicitly excludes.

## What is NOT done, and why

Per the Phase 2 scope, this phase intentionally stops at the flag +
abstraction + working `cnsa2` signature profile:

- **No ML-KEM-1024** (see above — no existing key-exchange call site to
  attach it to).
- **No default change.** `commercial` (ML-DSA-65) remains the default for
  every existing caller; nothing signs with ML-DSA-87 unless a caller
  explicitly opts in with `profile="cnsa2"` or sets `PQC_PROFILE=cnsa2`.
- **No mixed-profile verification.** A `cnsa2`-signed entry cannot be
  verified by a `commercial`-profile manager's key (different keypair
  entirely) — expected and tested
  (`test_commercial_and_cnsa2_signatures_are_not_cross_verifiable`), not
  a bug.

## Operating it

```bash
# Default -- no action needed, matches every existing deployment.
# PQC_PROFILE unset -> "commercial" -> ML-DSA-65

# Opt into CNSA 2.0 signatures for new signing activity:
export PQC_PROFILE=cnsa2
```

Restarting JAKAL with `PQC_PROFILE=cnsa2` set generates a fresh ML-DSA-87
keypair on next `PQCAuditManager()` construction (keys are per-process,
not persisted across restarts today — see `pqc_manager.py`'s own
docstring) and every subsequently signed audit entry uses ML-DSA-87.
Previously-signed ML-DSA-65 entries remain in `pqc_audit_log` unchanged
and still verify correctly under their own recorded `algorithm`/public
key — a profile switch is forward-only for new signatures, never a
retroactive re-sign.
