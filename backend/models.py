"""
JAKAL Models - Pydantic Validation & Serialization Schemas
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Base / Common ──────────────────────────────────────────────────────────

class StatusResponse(BaseModel):
    status: str
    message: Optional[str] = None


# ── Pentest & Findings Models ──────────────────────────────────────────────

class PentestRunCreate(BaseModel):
    target: str
    scan_type: str = Field(default="comprehensive")


class FindingBase(BaseModel):
    severity: str
    title: str
    description: str
    attack_technique: Optional[str] = None
    remediation: Optional[str] = None


class FindingCreate(FindingBase):
    pentest_id: int


# ── Payload Execution & Authorization Models ───────────────────────────────

class PayloadExecutionRequest(BaseModel):
    execution_id: str
    pentest_id: Optional[int] = None
    target: str
    phase: str
    command: str
    technique_id: Optional[str] = None
    tool: Optional[str] = None
    risk_level: Optional[str] = Field(default="MEDIUM")
    operator_id: str
    authorized: bool = False


class ApprovalRequestCreate(BaseModel):
    request_id: str
    requested_by: str
    action_type: str
    target: Optional[str] = None
    phase: Optional[str] = None
    technique_id: Optional[str] = None
    risk_level: Optional[str] = Field(default="MEDIUM")
    summary: Optional[str] = None
    payload_detail: Optional[Dict[str, Any]] = Field(default_factory=dict)
    expires_at: Optional[datetime] = None


class ApprovalDecision(BaseModel):
    decided_by: str
    status: str  # approved / rejected
    decision_reason: Optional[str] = None


# ── Quantum & PQC Audit Models ─────────────────────────────────────────────

class QuantumJobCreate(BaseModel):
    job_id: str
    circuit_name: str
    backend: str = Field(default="simulator")
    shots: int = Field(default=1024)


class PQCAuditLogEntry(BaseModel):
    entry_id: str
    agent_id: str
    operator_id: str
    action_type: str
    action_detail: str
    payload_hash: str
    pqc_signature: str
    algorithm: str
    public_key: str
    chain_index: int = 0
    prev_hash: Optional[str] = None


# ── v2.5 Ares Control Plane & Resonance Policy Models ──────────────────────

class ResonancePolicyCreate(BaseModel):
    policy_id: str
    policy_name: str
    description: Optional[str] = None
    threat_threshold: float = Field(default=0.7)
    trigger_type: str = Field(default="threat_detection")
    isolation_mode: str = Field(default="network_only")
    auto_enforce: bool = Field(default=False)
    webhook_url: Optional[str] = None
    enabled: bool = Field(default=True)


class ResonancePolicyUpdate(BaseModel):
    policy_name: Optional[str] = None
    description: Optional[str] = None
    threat_threshold: Optional[float] = None
    trigger_type: Optional[str] = None
    isolation_mode: Optional[str] = None
    auto_enforce: Optional[bool] = None
    webhook_url: Optional[str] = None
    enabled: Optional[bool] = None


class UnifiedSecurityEventCreate(BaseModel):
    event_id: str
    source_module: str
    threat_category: Optional[str] = None
    severity_score: float = Field(default=0.0)
    raw_payload: Optional[Dict[str, Any]] = Field(default_factory=dict)
    approval_request_id: Optional[str] = None