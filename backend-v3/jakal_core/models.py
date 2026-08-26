"""SQLAlchemy 2.0 typed models for the JAKAL persistence layer.

Design decisions driven by the teardown findings:

* Primary keys are application-generated UUIDs (``uuid.uuid4``), not a shared
  DB sequence. This removes the duplicate-``id:1`` collision (GAP-03) that came
  from many connections sharing one sequence file, and lets any node mint an id
  without a round-trip.
* ``sqlalchemy.Uuid`` maps to native ``uuid`` on Postgres and ``CHAR(32)`` on
  SQLite — one model, two engines.
* Every mutable row carries ``created_at`` and, where it changes, ``updated_at``
  (server-defaulted) for audit.
* Status/role/lifecycle are real ``Enum`` columns, not free-text strings.

Coverage maps to the requested API surfaces:
    Operator ............................ auth / RBAC (all /api)
    UnifiedSecurityEvent ................ /api/ares/, /api/qaip/
    PQCAuditEntry ....................... /api/crypto/ audit log
    EncryptionKey / KeyRotationHistory .. /api/crypto/ key lifecycle
    ApprovalRequest ..................... /api/approval/ human gate
    RemediationTask ..................... /api/canvas/ patch pipeline
    FabricCapability / PostureAssessment  /api/fabric/ ZT posture
    AISafetyEvent ....................... /api/horizon/
    QuantumJob / OrbitalComm ............ /api/quantum/, /api/qaip/
    PayloadExecution .................... /api/payloads/, /api/aip/
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────
class Role(str, PyEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


class RiskLevel(str, PyEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ApprovalStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class KeyStatus(str, PyEnum):
    ACTIVE = "active"
    ROTATED = "rotated"
    REVOKED = "revoked"


class TaskStatus(str, PyEnum):
    QUEUED = "queued"
    AWAITING_APPROVAL = "awaiting_approval"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class JobStatus(str, PyEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MaturityLevel(str, PyEnum):
    # NSA/CISA Zero Trust Maturity ladder
    TRADITIONAL = "traditional"
    INITIAL = "initial"
    ADVANCED = "advanced"
    OPTIMAL = "optimal"


# ─────────────────────────────────────────────────────────────────────────────
# Identity / RBAC  (GAP-01)
# ─────────────────────────────────────────────────────────────────────────────
class Operator(Base):
    __tablename__ = "operators"

    operator_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.VIEWER, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cross-pillar event bus  (/api/ares/, /api/qaip/)
# ─────────────────────────────────────────────────────────────────────────────
class UnifiedSecurityEvent(Base):
    __tablename__ = "unified_security_events"
    __table_args__ = (
        Index("ix_use_module_cat", "source_module", "threat_category"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    source_module: Mapped[str] = mapped_column(String(64), index=True)
    threat_category: Mapped[str | None] = mapped_column(String(64), index=True)
    severity_score: Mapped[float] = mapped_column(Float, default=0.0)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Nullable link to the approval this event staged (GAP: origin_module lives
    # in the approval row, not a parallel queue table).
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approval_requests.request_id", ondelete="SET NULL")
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# PQC audit log + key lifecycle  (/api/crypto/)
# ─────────────────────────────────────────────────────────────────────────────
class PQCAuditEntry(Base):
    __tablename__ = "pqc_audit_log"

    entry_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    operator_id: Mapped[str] = mapped_column(String(64), index=True)
    action_type: Mapped[str] = mapped_column(String(128))
    action_detail: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(128), index=True)
    # Crypto-agility (GAP-05 / SP 1800-38): the exact algorithm(s) used are
    # recorded per row so a verifier can enforce a policy and a future rollover
    # never orphans old signatures.
    algorithm: Mapped[str] = mapped_column(String(64))
    pqc_signature: Mapped[str] = mapped_column(Text)          # ML-DSA-65, hex
    classical_signature: Mapped[str | None] = mapped_column(Text)  # Ed25519, hex
    public_key: Mapped[str] = mapped_column(Text)
    classical_public_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )


class EncryptionKey(Base):
    __tablename__ = "encryption_keys"

    key_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    algorithm: Mapped[str] = mapped_column(String(64))       # e.g. AES-256-GCM
    purpose: Mapped[str] = mapped_column(String(64), default="data-at-rest")
    status: Mapped[KeyStatus] = mapped_column(
        Enum(KeyStatus), default=KeyStatus.ACTIVE, index=True
    )
    # The data key is stored ONLY envelope-wrapped under the KEK/KMS master key.
    wrapped_key: Mapped[bytes] = mapped_column()
    wrap_nonce: Mapped[bytes] = mapped_column()
    key_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rotations: Mapped[list[KeyRotationHistory]] = relationship(
        back_populates="old_key",
        foreign_keys="KeyRotationHistory.old_key_id",
        cascade="all, delete-orphan",
    )


class KeyRotationHistory(Base):
    __tablename__ = "key_rotation_history"

    rotation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    old_key_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("encryption_keys.key_id", ondelete="CASCADE"), index=True
    )
    new_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("encryption_keys.key_id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(255), default="")
    rotated_by: Mapped[str] = mapped_column(String(64))
    rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    old_key: Mapped[EncryptionKey] = relationship(
        back_populates="rotations", foreign_keys=[old_key_id]
    )


# ─────────────────────────────────────────────────────────────────────────────
# Human Approval Gate  (/api/approval/)
# ─────────────────────────────────────────────────────────────────────────────
class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    requested_by: Mapped[str] = mapped_column(String(64), index=True)
    action_type: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str | None] = mapped_column(String(255))
    phase: Mapped[str | None] = mapped_column(String(64))
    technique_id: Mapped[str | None] = mapped_column(String(32))
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel), default=RiskLevel.MEDIUM, index=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), default=ApprovalStatus.PENDING, index=True
    )
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    origin_module: Mapped[str | None] = mapped_column(String(64))
    pqc_entry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ─────────────────────────────────────────────────────────────────────────────
# Agentic Canvas  (/api/canvas/)
# ─────────────────────────────────────────────────────────────────────────────
class RemediationTask(Base):
    __tablename__ = "agentic_remediation_tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    target_machine_ip: Mapped[str] = mapped_column(String(64), index=True)
    patch_id: Mapped[str] = mapped_column(String(128))
    autonomous_action_taken: Mapped[str] = mapped_column(Text, default="")
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_requests.request_id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.AWAITING_APPROVAL, index=True
    )
    deployment_progress: Mapped[int] = mapped_column(Integer, default=0)
    rollback_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Unified Security Fabric — Zero Trust posture  (/api/fabric/)
# ─────────────────────────────────────────────────────────────────────────────
class FabricCapability(Base):
    __tablename__ = "fabric_modules"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    pillar: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    maturity: Mapped[MaturityLevel] = mapped_column(
        Enum(MaturityLevel), default=MaturityLevel.INITIAL
    )
    operational_status: Mapped[str] = mapped_column(String(32), default="active")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )


class PostureAssessment(Base):
    __tablename__ = "zt_posture_assessments"

    assessment_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    overall_score: Mapped[float] = mapped_column(Float)
    overall_level: Mapped[MaturityLevel] = mapped_column(Enum(MaturityLevel))
    per_pillar: Mapped[dict] = mapped_column(JSON, default=dict)
    operator_id: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# Horizon AI-safety  (/api/horizon/)
# ─────────────────────────────────────────────────────────────────────────────
class AISafetyEvent(Base):
    __tablename__ = "ai_safety_events"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    soc_compliance_tier: Mapped[str] = mapped_column(String(64), default="SOC2 Type II")
    protection_layer: Mapped[str] = mapped_column(String(64), default="ai-agent-layer")
    alert_severity: Mapped[int] = mapped_column(Integer, default=1, index=True)
    regulatory_schema_status: Mapped[str] = mapped_column(String(64), default="Syncing")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# Quantum job queue + orbital telemetry  (/api/quantum/, /api/qaip/)
# ─────────────────────────────────────────────────────────────────────────────
class QuantumJob(Base):
    __tablename__ = "quantum_jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    circuit_name: Mapped[str] = mapped_column(String(64))
    backend: Mapped[str] = mapped_column(String(64), default="aer_simulator")
    shots: Mapped[int] = mapped_column(Integer, default=1024)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.QUEUED, index=True
    )
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrbitalComm(Base):
    __tablename__ = "quantum_orbital_comms"

    comm_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    computational_agent_id: Mapped[str] = mapped_column(String(64), default="")
    inference_chain_hash: Mapped[str] = mapped_column(String(128), default="")
    quantum_entropy_seed: Mapped[str] = mapped_column(String(128), default="")
    execution_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# AIP payload execution log  (/api/payloads/, /api/aip/)
# ─────────────────────────────────────────────────────────────────────────────
class PayloadExecution(Base):
    __tablename__ = "payload_executions"

    execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    payload_id: Mapped[str] = mapped_column(String(64), index=True)
    technique_id: Mapped[str | None] = mapped_column(String(32), index=True)
    target: Mapped[str] = mapped_column(String(255))
    phase: Mapped[str | None] = mapped_column(String(64))
    ontology_refs: Mapped[dict] = mapped_column(JSON, default=dict)  # cheatsheet interweave
    command_set: Mapped[dict] = mapped_column(JSON, default=dict)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    result: Mapped[dict | None] = mapped_column(JSON)
    operator_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )
