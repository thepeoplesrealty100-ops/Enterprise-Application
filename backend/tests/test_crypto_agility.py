"""
backend/tests/test_crypto_agility.py
JAKAL v3.0 Phase 2 -- PQC crypto-agility / CNSA 2.0 readiness.

PQCAuditManager's signer is now selected by a PQC_PROFILE (config flag,
default "commercial" -> ML-DSA-65/Dilithium3). A second, already-working
profile ("cnsa2" -> ML-DSA-87/Dilithium5) exists to prove the abstraction
is real and not just a stub -- dilithium-py already ships Dilithium5
cleanly, so switching profiles genuinely is "a configuration change + key
regeneration, not a rewrite" (docs/crypto-agility.md). Every existing call
site still constructs PQCAuditManager() with no args and must keep
signing with ML-DSA-65 exactly as before this phase.

Run: cd backend && python -m pytest tests/test_crypto_agility.py -q
"""

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from crypto.pqc_manager import PQCAuditManager, PQC_PARAMETER_SETS, DEFAULT_PQC_PROFILE


def test_default_profile_is_commercial_ml_dsa_65():
    """No behavior change: PQCAuditManager() with no args must keep
    signing with ML-DSA-65, exactly as every existing call site expects."""
    mgr = PQCAuditManager()
    assert mgr.profile == "commercial"
    assert mgr.algorithm == "ML-DSA-65 (Dilithium3)"
    assert DEFAULT_PQC_PROFILE == "commercial"


def test_cnsa2_profile_selects_ml_dsa_87():
    mgr = PQCAuditManager(profile="cnsa2")
    assert mgr.profile == "cnsa2"
    assert mgr.algorithm == "ML-DSA-87 (Dilithium5)"


def test_cnsa2_profile_sign_verify_round_trip():
    mgr = PQCAuditManager(profile="cnsa2")
    signed = mgr.sign_agent_action("test-agent", {"action_type": "noop", "x": 1}, "op1")
    assert mgr.verify_audit_log(signed) is True
    assert mgr.verify_payload_integrity(signed) is True


def test_commercial_and_cnsa2_signatures_are_not_cross_verifiable():
    """Different parameter sets -> different keypairs; a cnsa2-signed
    entry must not verify under a commercial-profile manager's key."""
    commercial = PQCAuditManager(profile="commercial")
    cnsa2 = PQCAuditManager(profile="cnsa2")
    signed_by_cnsa2 = cnsa2.sign_agent_action("test-agent", {"action_type": "noop", "x": 2}, "op1")
    assert commercial.verify_audit_log(signed_by_cnsa2) is False


def test_unknown_profile_falls_back_to_commercial_not_error():
    mgr = PQCAuditManager(profile="quantum-supremacy-2099")
    assert mgr.profile == "commercial"
    assert mgr.algorithm == "ML-DSA-65 (Dilithium3)"


def test_status_reports_profile_and_available_profiles():
    mgr = PQCAuditManager()
    status = mgr.status()
    assert status["profile"] == "commercial"
    assert set(status["available_profiles"]) == {"commercial", "cnsa2"}


def test_parameter_sets_registry_shape():
    """Sanity-check the registry itself stays a simple, extensible map --
    no caller anywhere should need to hardcode a Dilithium class name."""
    assert PQC_PARAMETER_SETS["commercial"] == {"dilithium_cls": "Dilithium3", "label": "ML-DSA-65"}
    assert PQC_PARAMETER_SETS["cnsa2"] == {"dilithium_cls": "Dilithium5", "label": "ML-DSA-87"}


def test_config_pqc_profile_flag_exists():
    """No reload here -- Config reads PQC_PROFILE once at import time like
    every other env-driven setting in this class, so this just confirms
    the flag exists and honors whatever the process environment set it to
    (falling back to 'commercial' when unset), without fighting module
    caching or other tests' import order."""
    import os
    from config import Config
    expected = os.environ.get("PQC_PROFILE", "commercial")
    assert Config.PQC_PROFILE == expected
