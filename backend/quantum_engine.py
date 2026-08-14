# JAKAL Quantum Engine - Qiskit Integration & Simulation Suite
#
# Everything in this module is SIMULATION or genuine small-scale quantum
# computation run on Qiskit-Aer (and optionally real IBM hardware via
# Qiskit Runtime for the tiny demo circuits). None of it performs real
# cryptanalysis or has any actual bearing on breaking real-world crypto --
# that requires millions of physical qubits with error correction, which
# doesn't exist yet. The "brute force cost estimate" panel is a pure
# arithmetic illustration of Grover's quadratic speedup, not a working
# attack against anything.

import logging
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
    from qiskit_aer import AerSimulator
    from qiskit_ibm_runtime import QiskitRuntimeService
    QISKIT_AVAILABLE = True
except ImportError:
    QISKIT_AVAILABLE = False
    logging.warning("Qiskit not installed. Quantum functionality will be limited.")

logger = logging.getLogger(__name__)


class QuantumEngine:
    """Quantum computing engine with Qiskit integration + simulation panels."""

    def __init__(self, config=None):
        self.config = config
        self.simulator = AerSimulator() if QISKIT_AVAILABLE else None
        self.ibm_service = None
        self.job_cache: Dict[str, Any] = {}
        self.initialize_ibm_service()

    def initialize_ibm_service(self):
        token = getattr(self.config, "IBM_QUANTUM_TOKEN", None) if self.config else None
        if token and QISKIT_AVAILABLE:
            try:
                channel = getattr(self.config, "IBM_QUANTUM_CHANNEL", "ibm_quantum")
                QiskitRuntimeService.save_account(channel=channel, token=token, overwrite=True)
                self.ibm_service = QiskitRuntimeService(channel=channel)
                logger.info("IBM Quantum Runtime service initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize IBM Quantum service: {e}")
                self.ibm_service = None
        else:
            logger.info("IBM Quantum token not configured. Using local Aer simulator only.")

    # ------------------------------------------------------------------
    # Circuits
    # ------------------------------------------------------------------

    def create_bell_state_circuit(self, num_qubits: int = 2) -> "QuantumCircuit":
        qr = QuantumRegister(num_qubits, "q")
        cr = ClassicalRegister(num_qubits, "c")
        circuit = QuantumCircuit(qr, cr, name="bell_state")
        circuit.h(qr[0])
        for i in range(1, num_qubits):
            circuit.cx(qr[0], qr[i])
        circuit.measure(qr, cr)
        return circuit

    def create_grover_circuit(self, num_qubits: int = 3) -> "QuantumCircuit":
        qr = QuantumRegister(num_qubits, "q")
        cr = ClassicalRegister(num_qubits, "c")
        circuit = QuantumCircuit(qr, cr, name="grover_search")
        for i in range(num_qubits):
            circuit.h(qr[i])
        circuit.x(qr[0])
        circuit.h(qr[num_qubits - 1])
        for i in range(num_qubits - 1):
            circuit.cx(qr[i], qr[num_qubits - 1])
        circuit.h(qr[num_qubits - 1])
        circuit.x(qr[0])
        for i in range(num_qubits):
            circuit.h(qr[i])
        for i in range(num_qubits):
            circuit.x(qr[i])
        circuit.h(qr[num_qubits - 1])
        for i in range(num_qubits - 1):
            circuit.cx(qr[i], qr[num_qubits - 1])
        circuit.h(qr[num_qubits - 1])
        for i in range(num_qubits):
            circuit.x(qr[i])
        for i in range(num_qubits):
            circuit.h(qr[i])
        circuit.measure(qr, cr)
        return circuit

    def create_qaoa_circuit(self, num_qubits: int = 4, layers: int = 1) -> "QuantumCircuit":
        qr = QuantumRegister(num_qubits, "q")
        cr = ClassicalRegister(num_qubits, "c")
        circuit = QuantumCircuit(qr, cr, name="qaoa")
        for i in range(num_qubits):
            circuit.h(qr[i])
        for _ in range(layers):
            for i in range(num_qubits - 1):
                circuit.rzz(0.5, qr[i], qr[i + 1])
            for i in range(num_qubits):
                circuit.rx(0.5, qr[i])
        circuit.measure(qr, cr)
        return circuit

    def create_qrng_circuit(self, num_bits: int = 8) -> "QuantumCircuit":
        """True quantum random number generator: qubits in equal superposition,
        measured. Unlike a classical PRNG, each bit is genuinely non-deterministic
        (assuming no simulator determinism -- on real hardware this is a
        legitimate source of entropy)."""
        qr = QuantumRegister(num_bits, "q")
        cr = ClassicalRegister(num_bits, "c")
        circuit = QuantumCircuit(qr, cr, name="qrng")
        for i in range(num_bits):
            circuit.h(qr[i])
        circuit.measure(qr, cr)
        return circuit

    def create_ghz_circuit(self, num_qubits: int = 4) -> "QuantumCircuit":
        """Multi-qubit entanglement (generalizes Bell state). Useful demo panel
        for showing entanglement scaling / entropy across more qubits."""
        qr = QuantumRegister(num_qubits, "q")
        cr = ClassicalRegister(num_qubits, "c")
        circuit = QuantumCircuit(qr, cr, name="ghz_state")
        circuit.h(qr[0])
        for i in range(1, num_qubits):
            circuit.cx(qr[0], qr[i])
        circuit.measure(qr, cr)
        return circuit

    def create_deutsch_jozsa_circuit(self, num_qubits: int = 3, balanced: bool = True) -> "QuantumCircuit":
        """Classic demonstration of quantum query advantage: determines whether
        a black-box function is constant or balanced in one query instead of
        exponentially many classical queries. Good dashboard talking point for
        'what quantum actually buys you' without overselling it."""
        qr = QuantumRegister(num_qubits + 1, "q")
        cr = ClassicalRegister(num_qubits, "c")
        circuit = QuantumCircuit(qr, cr, name="deutsch_jozsa")
        circuit.x(qr[num_qubits])
        for i in range(num_qubits + 1):
            circuit.h(qr[i])
        if balanced:
            for i in range(num_qubits):
                circuit.cx(qr[i], qr[num_qubits])
        for i in range(num_qubits):
            circuit.h(qr[i])
        circuit.measure(qr[:num_qubits], cr)
        return circuit

    CIRCUIT_BUILDERS = {
        "bell_state": "create_bell_state_circuit",
        "grover": "create_grover_circuit",
        "qaoa": "create_qaoa_circuit",
        "qrng": "create_qrng_circuit",
        "ghz": "create_ghz_circuit",
        "deutsch_jozsa": "create_deutsch_jozsa_circuit",
    }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_circuit(self, circuit_name: str, shots: int = 1024, backend: str = "qiskit_aer") -> Dict[str, Any]:
        if not QISKIT_AVAILABLE:
            return {"status": "error", "error": "qiskit not installed", "backend": backend}

        start_time = time.time()
        try:
            builder_name = self.CIRCUIT_BUILDERS.get(circuit_name)
            if not builder_name:
                raise ValueError(f"Unknown circuit: {circuit_name}. Available: {list(self.CIRCUIT_BUILDERS)}")
            circuit = getattr(self, builder_name)()

            if backend == "ibm_hardware" and self.ibm_service:
                job = self._run_on_ibm_hardware(circuit, shots)
                return {
                    "job_id": job.job_id(),
                    "status": "submitted",
                    "backend": "ibm_hardware",
                    "message": "Job submitted to IBM Quantum. Poll with the job ID for results.",
                    "execution_time_ms": (time.time() - start_time) * 1000,
                }

            result = self._run_on_aer_simulator(circuit, shots)
            result["execution_time_ms"] = (time.time() - start_time) * 1000
            return result

        except Exception as e:
            logger.error(f"Circuit execution failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "backend": backend,
                "execution_time_ms": (time.time() - start_time) * 1000,
            }

    def _run_on_aer_simulator(self, circuit: "QuantumCircuit", shots: int) -> Dict[str, Any]:
        transpiled = transpile(circuit, self.simulator, optimization_level=2)
        job = self.simulator.run(transpiled, shots=shots)
        result = job.result()
        counts = result.get_counts(0)
        return {
            "status": "completed",
            "backend": "qiskit_aer",
            "counts": counts,
            "shots": shots,
            "circuit_name": circuit.name,
            "circuit_depth": transpiled.depth(),
            "num_qubits": circuit.num_qubits,
            "message": "Quantum simulation completed successfully",
        }

    def _run_on_ibm_hardware(self, circuit: "QuantumCircuit", shots: int):
        from qiskit_ibm_runtime import Batch
        # Backend name should come from config, not hardcoded -- IBM retires/
        # renames backends periodically. Falls back to least-busy if unset.
        backend_name = getattr(self.config, "IBM_BACKEND_NAME", None) if self.config else None
        with Batch(service=self.ibm_service, backend=backend_name) as batch:
            return batch.run(circuit, shots=shots)

    # ------------------------------------------------------------------
    # Storage / retrieval
    # ------------------------------------------------------------------

    def store_result(self, result: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        self.job_cache[job_id] = result
        return job_id

    def retrieve_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.job_cache.get(job_id)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze_results(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if result.get("status") != "completed":
            return {"analysis": "Results not ready or error occurred"}

        counts = result.get("counts", {})
        shots = result.get("shots", 1024)
        probabilities = {state: count / shots for state, count in counts.items()}
        most_likely = max(counts, key=counts.get) if counts else None
        most_likely_prob = (counts.get(most_likely, 0) / shots) if most_likely else 0

        return {
            "status": "analyzed",
            "most_likely_state": most_likely,
            "most_likely_probability": most_likely_prob,
            "all_probabilities": probabilities,
            "entropy": self._calculate_entropy(probabilities),
            "top_3_states": sorted(probabilities.items(), key=lambda x: x[1], reverse=True)[:3],
        }

    @staticmethod
    def _calculate_entropy(probabilities: Dict[str, float]) -> float:
        entropy = 0.0
        for p in probabilities.values():
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    # ------------------------------------------------------------------
    # "Full experience" simulation panel: Grover speedup cost estimate
    # ------------------------------------------------------------------
    #
    # This is pure arithmetic (no live target, no real search), suitable
    # for a dashboard panel that illustrates *why* quantum-resistant crypto
    # is being adopted -- it does NOT perform or enable any actual attack.

    def estimate_grover_speedup(self, keyspace_bits: int) -> Dict[str, Any]:
        """
        Illustrates the quadratic speedup Grover's algorithm offers in
        THEORY for unstructured search (e.g. brute-forcing a symmetric key),
        assuming a large fault-tolerant quantum computer existed -- which it
        does not, today. Real AES-256 is considered Grover-resistant in
        practice because it would still need ~2^128 operations even under
        Grover, which remains computationally infeasible.
        """
        classical_ops = 2 ** keyspace_bits
        grover_ops = 2 ** (keyspace_bits / 2)

        return {
            "keyspace_bits": keyspace_bits,
            "classical_operations_estimate": classical_ops,
            "grover_operations_estimate": grover_ops,
            "theoretical_speedup_factor": classical_ops / grover_ops if grover_ops else None,
            "effective_security_bits_under_grover": keyspace_bits / 2,
            "caveat": (
                "Theoretical only. Requires a large-scale fault-tolerant quantum "
                "computer that does not currently exist. Not an executable attack."
            ),
        }

    def quantum_risk_panel(self) -> Dict[str, Any]:
        """Aggregates a few illustrative estimates for common key sizes,
        for a dashboard 'quantum readiness' panel."""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "algorithms": [
                {"name": "AES-128", "keyspace_bits": 128, **self.estimate_grover_speedup(128)},
                {"name": "AES-256", "keyspace_bits": 256, **self.estimate_grover_speedup(256)},
                {"name": "RSA-2048 (Shor-vulnerable, not Grover)", "keyspace_bits": None,
                 "note": "RSA/ECC are broken by Shor's algorithm, not Grover's -- a "
                         "structurally different (factoring) problem needing a much "
                         "larger fault-tolerant machine than exists today."},
            ],
            "recommendation": "Migrate long-lived secrets to NIST PQC algorithms "
                               "(ML-KEM / ML-DSA) regardless of current quantum "
                               "hardware timelines -- 'harvest now, decrypt later' "
                               "is the realistic near-term risk, not a live quantum attack.",
        }
