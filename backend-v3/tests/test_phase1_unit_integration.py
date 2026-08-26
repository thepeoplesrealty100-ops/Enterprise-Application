"""Phase 1 — unit & integration tests (20 cases).

Covers PQC key/sign/verify chains, key lifecycle, the Ares rollup + unified
event stream, AIP-style payload staging through the approval gate, and the
identity gate. Every test runs against a fresh isolated database.
"""
from __future__ import annotations

import uuid

import pytest

from jakal_core import auth, config
from jakal_core.crypto.pqc import ALGO_HYBRID, MLDSA_AVAILABLE, HybridSigner
from jakal_core.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    SeparationOfDutiesError,
)
from jakal_core.models import ApprovalStatus, KeyStatus, RiskLevel, Role

pytestmark = pytest.mark.asyncio


# ── PQC signing chain (5) ───────────────────────────────────────────────────
async def test_01_pqc_backend_is_real_mldsa():
    assert MLDSA_AVAILABLE, "ML-DSA-65 backend must be present for a PQC claim"
    assert HybridSigner().algorithm == ALGO_HYBRID


async def test_02_sign_then_verify_roundtrips(crypto):
    entry = await crypto.sign_agent_action("recon", {"target": "10.0.0.1"}, "op-alice")
    assert entry.algorithm == ALGO_HYBRID
    assert await crypto.verify_entry(entry.entry_id) is True


async def test_03_tampered_payload_fails_verification(crypto, session):
    entry = await crypto.sign_agent_action("recon", {"target": "10.0.0.1"}, "op-alice")
    entry.action_detail = '{"target": "10.0.0.2"}'  # tamper after signing
    await session.flush()
    assert await crypto.verify_entry(entry.entry_id) is False


async def test_04_strict_mode_requires_pqc_leg(strict_signer):
    msg = b"authorize"
    bundle = strict_signer.sign(msg)
    assert bundle.pqc_signature is not None
    # Drop the PQC leg → strict verify must fail even though classical is intact.
    downgraded = bundle.__class__(
        algorithm="Ed25519", pqc_signature=None,
        classical_signature=bundle.classical_signature,
        public_key=None, classical_public_key=bundle.classical_public_key,
    )
    assert strict_signer.verify(msg, downgraded, require_pqc=True) is False
    assert strict_signer.verify(msg, downgraded, require_pqc=False) is True


async def test_05_verify_unknown_entry_raises(crypto):
    with pytest.raises(NotFoundError):
        await crypto.verify_entry(uuid.uuid4())


# ── Key lifecycle (6) ───────────────────────────────────────────────────────
async def test_06_register_key_populates_table(crypto):
    key = await crypto.register_key()
    assert key.status is KeyStatus.ACTIVE
    assert key.wrapped_key and key.wrap_nonce  # stored wrapped, never plaintext


async def test_07_data_key_unwraps_to_stable_value(crypto):
    key = await crypto.register_key()
    a = await crypto.get_data_key(key.key_id)
    b = await crypto.get_data_key(key.key_id)
    assert a == b and len(a) == 32


async def test_08_rotation_keeps_old_key_decryptable_and_makes_new(crypto):
    old = await crypto.register_key()
    old_material = await crypto.get_data_key(old.key_id)
    new = await crypto.rotate_key(old.key_id, rotated_by="ad-carol", reason="scheduled")
    assert new.key_id != old.key_id
    # old still decryptable (status ROTATED, not REVOKED)
    assert await crypto.get_data_key(old.key_id) == old_material


async def test_09_rotate_missing_key_raises_not_false(crypto):
    with pytest.raises(NotFoundError):
        await crypto.rotate_key(uuid.uuid4(), rotated_by="ad-carol")


async def test_10_revoked_key_cannot_decrypt(crypto):
    key = await crypto.register_key()
    await crypto.revoke_key(key.key_id, revoked_by="ad-carol", reason="compromise")
    with pytest.raises(Exception):
        await crypto.get_data_key(key.key_id)


async def test_11_list_keys_status_none_returns_all_states(crypto):
    k1 = await crypto.register_key()
    await crypto.register_key()
    await crypto.revoke_key(k1.key_id, revoked_by="ad-carol")
    all_states = {k.status for k in await crypto.list_keys(status=None)}
    assert KeyStatus.ACTIVE in all_states and KeyStatus.REVOKED in all_states
    assert len(await crypto.list_keys(status=KeyStatus.REVOKED)) == 1


# ── Approval gate / AIP staging (5) ─────────────────────────────────────────
async def test_12_operator_can_stage_high_risk_request(approvals, principals):
    req = await approvals.create_request(
        principals["operator"], action_type="exploit_stage", target="10.0.0.5",
        risk_level=RiskLevel.HIGH, summary="stage T1190", payload_detail={"technique": "T1190"},
    )
    assert req.status is ApprovalStatus.PENDING


async def test_13_viewer_cannot_stage(approvals, principals):
    with pytest.raises(AuthorizationError):
        await approvals.create_request(
            principals["viewer"], action_type="exploit_stage", target="10.0.0.5",
            risk_level=RiskLevel.HIGH, summary="x", payload_detail={},
        )


async def test_14_separation_of_duties_requester_cannot_self_approve(approvals, principals):
    # A principal that is both operator and approver still cannot approve own req.
    dual = auth.Principal("op-alice", Role.APPROVER, "alice@x")  # same operator_id as requester
    req = await approvals.create_request(
        principals["operator"], action_type="patch", target="10.0.0.9",
        risk_level=RiskLevel.HIGH, summary="deploy", payload_detail={},
    )
    with pytest.raises(SeparationOfDutiesError):
        await approvals.decide(dual, req.request_id, approve=True)


async def test_15_execution_blocked_until_approved_then_allowed(approvals, principals):
    req = await approvals.create_request(
        principals["operator"], action_type="patch", target="10.0.0.9",
        risk_level=RiskLevel.HIGH, summary="deploy", payload_detail={},
    )
    blocked = await approvals.execute(principals["operator"], req.request_id)
    assert blocked["status"] == "blocked"
    await approvals.decide(principals["approver"], req.request_id, approve=True)
    ok = await approvals.execute(principals["operator"], req.request_id)
    assert ok["status"] == "executed"


async def test_16_double_execute_is_conflict(approvals, principals):
    req = await approvals.create_request(
        principals["operator"], action_type="patch", target="10.0.0.9",
        risk_level=RiskLevel.HIGH, summary="deploy", payload_detail={},
    )
    await approvals.decide(principals["approver"], req.request_id, approve=True)
    await approvals.execute(principals["operator"], req.request_id)
    with pytest.raises(ConflictError):
        await approvals.execute(principals["operator"], req.request_id)


# ── Ares rollup + events (2) ────────────────────────────────────────────────
async def test_17_global_matrix_uninitialized_with_no_fabric(ares):
    summary = await ares.global_matrix_summary()
    assert summary["fabric_status"] == "UNINITIALIZED"
    assert summary["derived"] is True


async def test_18_recon_to_matrix_cycle_counts_blocked_threat(ares, approvals, principals):
    req = await approvals.create_request(
        principals["operator"], action_type="qaip_recon_high", target="10.0.0.5",
        risk_level=RiskLevel.CRITICAL, summary="exposed svc", payload_detail={},
    )
    await approvals.decide(principals["approver"], req.request_id, approve=False)  # denied = gate acted
    await ares.record_event(
        source_module="GOD_S_EYE_RECON", threat_category="EXPOSED_SERVICE",
        severity_score=0.92, raw_payload={"svc": "rdp"}, approval_request_id=req.request_id,
    )
    summary = await ares.global_matrix_summary()
    assert summary["threats_blocked_count"] == 1


# ── Identity gate (2) ───────────────────────────────────────────────────────
async def test_19_valid_token_decodes_to_principal():
    s = config.get_settings()
    token = auth.issue_token("op-alice", Role.OPERATOR, settings=s)
    p = auth.decode_token(token, s)
    assert p.operator_id == "op-alice" and p.role is Role.OPERATOR


async def test_20_expired_and_tampered_tokens_rejected():
    s = config.get_settings()
    expired = auth.issue_token("op-alice", Role.OPERATOR, settings=s, expired=True)
    with pytest.raises(AuthenticationError):
        auth.decode_token(expired, s)
    good = auth.issue_token("op-alice", Role.OPERATOR, settings=s)
    with pytest.raises(AuthenticationError):
        auth.decode_token(good + "x", s)  # signature tamper
