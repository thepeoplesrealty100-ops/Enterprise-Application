"""
backend/schemas.py
Pydantic request/response schemas for the JAKAL API.
All API payloads are validated here before reaching route handlers.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


# ---------------------------------------------------------------------------
# Scope & Authorization
# ---------------------------------------------------------------------------

class ScopeAddRequest(BaseModel):
    client_name: str = Field(..., example="Alpha Inc")
    scope_definition: str = Field(
        ..., example="203.0.113.0/24, staging.client.com"
    )
    start_date: str = Field(..., example="2026-01-01T00:00:00")
    end_date: str = Field(..., example="2026-12-31T23:59:59")
    roe_document_path: Optional[str] = None


class ScopeValidateRequest(BaseModel):
    target: str = Field(..., example="203.0.113.10")
    operator_id: str = Field(default="system")


class InsuranceAddRequest(BaseModel):
    policy_number: str = Field(..., example="POL-2026-001")
    provider: str = Field(..., example="CyberShield LLC")
    coverage_amount: float = Field(..., example=5_000_000.0)
    expiry: str = Field(..., example="2027-01-01T00:00:00")


# ---------------------------------------------------------------------------
# Pentest
# ---------------------------------------------------------------------------

class PentestRunRequest(BaseModel):
    target: str = Field(..., example="staging.client.com")
    scan_type: str = Field(default="comprehensive", example="comprehensive")
    operator_id: str = Field(default="system")
    include_quantum_panel: bool = False


class PentestCancelRequest(BaseModel):
    operator_id: str = Field(default="system")
    reason: Optional[str] = None


class PentestResponse(BaseModel):
    test_id: str
    status: str
    report: Optional[Dict[str, Any]] = None
    report_markdown: Optional[str] = None


# ---------------------------------------------------------------------------
# Quantum
# ---------------------------------------------------------------------------

class QuantumJobRequest(BaseModel):
    circuit: str = Field(default="bell_state", example="bell_state")
    shots: int = Field(default=1024, ge=1, le=8192)
    backend: str = Field(default="qiskit_aer", example="qiskit_aer")


class QuantumJobResponse(BaseModel):
    job_id: str
    result: Dict[str, Any]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class ReportExportRequest(BaseModel):
    format: str = Field(default="json", example="json")
    operator_id: str = Field(default="system")


class AggregateReportRequest(BaseModel):
    scan_id: str
    results: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# EDR / MDR Playbooks
# ---------------------------------------------------------------------------

class PlaybookExecuteRequest(BaseModel):
    context: str = Field(default="")
    operator_id: str = Field(default="system")


class PlaybookStepCompleteRequest(BaseModel):
    notes: str = Field(default="")
    operator_id: str = Field(default="system")


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

class ComplianceReportRequest(BaseModel):
    framework: str = Field(default="NIST_CSF", example="NIST_CSF")
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    scope_id: Optional[str] = None
    operator_id: str = Field(default="system")


# ---------------------------------------------------------------------------
# VM Orchestrator
# ---------------------------------------------------------------------------

class VMCreateRequest(BaseModel):
    name: str = Field(default="unnamed")
    image_key: str = Field(default="ubuntu-lab")
    operator_id: str = Field(default="system")


class VMExecRequest(BaseModel):
    command: str = Field(..., example="ls -la /")
    operator_id: str = Field(default="system")


# ---------------------------------------------------------------------------
# Generic responses
# ---------------------------------------------------------------------------

class StatusResponse(BaseModel):
    status: str
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
