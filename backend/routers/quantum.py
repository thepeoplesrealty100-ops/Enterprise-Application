"""
backend/routers/quantum.py
FastAPI router for quantum-computing status and job submission.
"""

from fastapi import APIRouter, HTTPException

from schemas import QuantumJobRequest, QuantumJobResponse, StatusResponse

router = APIRouter(prefix="/quantum", tags=["quantum"])


# ---------------------------------------------------------------------------
# Lightweight Qiskit-Aer status check
# ---------------------------------------------------------------------------

def _check_qiskit() -> dict:
    try:
        from qiskit import QuantumCircuit
        from qiskit_aer import AerSimulator
        return {
            "available": True,
            "backend": "qiskit_aer",
            "simulator": AerSimulator().name,
        }
    except ImportError:
        return {
            "available": False,
            "backend": "qiskit_aer",
            "reason": "qiskit / qiskit-aer not installed",
        }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=StatusResponse)
async def quantum_status():
    """Return whether the Qiskit-Aer backend is available."""
    info = _check_qiskit()
    return StatusResponse(
        status="ready" if info["available"] else "unavailable",
        message=str(info),
    )


@router.post("/job", response_model=QuantumJobResponse)
async def run_quantum_job(req: QuantumJobRequest):
    """
    Run a named quantum circuit on the Qiskit-Aer simulator.

    Currently supports: ``bell_state``, ``ghz``, ``qft``.
    """
    info = _check_qiskit()
    if not info["available"]:
        raise HTTPException(status_code=503, detail="Qiskit-Aer not available")

    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator
    import uuid

    shots = req.shots
    circuit_name = req.circuit.lower()

    # Build requested circuit
    if circuit_name == "bell_state":
        qc = QuantumCircuit(2, 2)
        qc.h(0)
        qc.cx(0, 1)
        qc.measure([0, 1], [0, 1])

    elif circuit_name == "ghz":
        qc = QuantumCircuit(3, 3)
        qc.h(0)
        qc.cx(0, 1)
        qc.cx(1, 2)
        qc.measure([0, 1, 2], [0, 1, 2])

    elif circuit_name == "qft":
        from qiskit.circuit.library import QFT
        qc = QFT(3).decompose()
        qc.measure_all()

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown circuit '{circuit_name}'. Choose: bell_state, ghz, qft",
        )

    simulator = AerSimulator()
    compiled  = transpile(qc, simulator)
    job       = simulator.run(compiled, shots=shots)
    counts    = job.result().get_counts()

    return QuantumJobResponse(
        job_id=str(uuid.uuid4()),
        result={
            "circuit": circuit_name,
            "shots":   shots,
            "counts":  counts,
        },
    )
