"""
backend/routers/quantum.py
==========================
Quantum job API — real QuantumEngine (JAKAL v2.5).

Preserves frontend contracts:
  POST /api/quantum/submit
  GET  /api/quantum/jobs/{job_id}
  GET  /api/quantum/risk-panel
  GET  /api/quantum/health

Also exposes /status as a lightweight availability check.

v3.0 Phase 4.4: when a submitted job actually finishes (the qiskit_aer
simulator path, which is synchronous -- NOT the ibm_hardware path, which
returns "submitted" and completes asynchronously with no completion
callback in this codebase to hook), it's PQC-signed and registered into
the existing q_aip_inference_registry audit trail (built for exactly
this in the original v3.0 Ontology work), optionally tagged with
related_approval_id if the caller names one. Best-effort: a linking
failure never blocks the job result from being returned.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from schemas import QuantumJobRequest, QuantumJobResponse, StatusResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/quantum", tags=["quantum"])

try:
    from config import get_config
    from quantum_engine import QuantumEngine, QISKIT_AVAILABLE
    from database import get_db_manager

    _config = get_config()
    _quantum = QuantumEngine(_config)
    _db = get_db_manager()
    _READY = True
    _ERR: Optional[str] = None
except Exception as exc:  # noqa: BLE001
    _READY = False
    _ERR = str(exc)
    _quantum = None
    _db = None
    QISKIT_AVAILABLE = False  # type: ignore


def _require() -> None:
    if not _READY:
        raise HTTPException(status_code=503, detail=f"Quantum engine unavailable: {_ERR}")


@router.get("/status", response_model=StatusResponse)
async def quantum_status():
    """Lightweight Qiskit / IBM availability check."""
    _require()
    return StatusResponse(
        status="ready" if QISKIT_AVAILABLE else "unavailable",
        message=(
            f"qiskit_available={QISKIT_AVAILABLE}; "
            f"ibm_service_connected={_quantum.ibm_service is not None}"
        ),
    )


@router.get("/health")
async def quantum_health():
    """Same shape previously served from app.py."""
    _require()
    return {
        "qiskit_available": QISKIT_AVAILABLE,
        "ibm_service_connected": _quantum.ibm_service is not None,
    }


@router.post("/submit", response_model=QuantumJobResponse)
async def submit_quantum_job(req: QuantumJobRequest):
    """Run a named circuit via QuantumEngine and cache the result."""
    _require()
    result = _quantum.run_circuit(req.circuit, req.shots, req.backend)
    job_id = _quantum.store_result(result)
    try:
        _db.record_quantum_job(
            job_id, req.circuit, result.get("backend", req.backend), req.shots,
            result, result.get("status", "unknown"),
        )
    except Exception as e:
        # Durability is a bonus on top of the in-memory cache above, which
        # already has the result -- never fail the request over this.
        logger.warning("Failed to persist quantum job %s to quantum_jobs: %s", job_id, e)
    qaip_inference_id = None
    if result.get("status") == "completed":
        qaip_inference_id = _link_finished_job_to_audit_trail(job_id, req, result)
    return QuantumJobResponse(job_id=job_id, result=result, qaip_inference_id=qaip_inference_id)


def _link_finished_job_to_audit_trail(
    job_id: str, req: QuantumJobRequest, result: Dict[str, Any],
) -> Optional[str]:
    """v3.0 Phase 4.4. See module docstring."""
    try:
        from database import get_db_manager
        from crypto.pqc_manager import PQCAuditManager
        db = get_db_manager()
        pqc = PQCAuditManager(db=db)
        metrics = {
            "job_id": job_id,
            "shots": result.get("shots"),
            "circuit_depth": result.get("circuit_depth"),
            "num_qubits": result.get("num_qubits"),
            "execution_time_ms": result.get("execution_time_ms"),
            "backend": result.get("backend"),
        }
        if req.related_approval_id:
            metrics["related_approval_id"] = req.related_approval_id
        signed = pqc.sign_agent_action(
            agent_id="quantum-engine",
            action_payload={"action_type": "quantum_job_completed", "job_id": job_id, **metrics},
            operator_id=req.operator_id,
        )
        return db.register_qaip_inference(
            circuit_type=req.circuit, metrics=metrics,
            pqc_signature=signed["pqc_signature"], operator_id=req.operator_id,
        )
    except Exception as e:
        logger.warning("Quantum job -> PQC audit trail linking failed for %s: %s", job_id, e)
        return None


@router.get("/jobs/{job_id}")
async def get_quantum_job(job_id: str):
    _require()
    result = _quantum.retrieve_result(job_id)
    if result is None:
        # Not in this process's in-memory cache -- fall back to the
        # durable record (a restart since submission, or a job submitted
        # against a different QuantumEngine instance, e.g. pentest.py's
        # own separate one).
        result = _db.get_quantum_job(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="job not found")
    return result


@router.get("/risk-panel")
async def quantum_risk_panel():
    """Illustrative Grover/Shor dashboard panel (not an executable attack)."""
    _require()
    return _quantum.quantum_risk_panel()
