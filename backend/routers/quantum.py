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
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from schemas import QuantumJobRequest, QuantumJobResponse, StatusResponse

router = APIRouter(prefix="/quantum", tags=["quantum"])

try:
    from config import get_config
    from quantum_engine import QuantumEngine, QISKIT_AVAILABLE

    _config = get_config()
    _quantum = QuantumEngine(_config)
    _READY = True
    _ERR: Optional[str] = None
except Exception as exc:  # noqa: BLE001
    _READY = False
    _ERR = str(exc)
    _quantum = None
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
    return QuantumJobResponse(job_id=job_id, result=result)


@router.get("/jobs/{job_id}")
async def get_quantum_job(job_id: str):
    _require()
    result = _quantum.retrieve_result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="job not found")
    return result


@router.get("/risk-panel")
async def quantum_risk_panel():
    """Illustrative Grover/Shor dashboard panel (not an executable attack)."""
    _require()
    return _quantum.quantum_risk_panel()
