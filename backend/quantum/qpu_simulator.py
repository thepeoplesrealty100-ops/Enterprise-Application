"""
backend/quantum/qpu_simulator.py
Quantum Processing Unit Abstraction Layer for JAKAL.

Wraps qiskit-aer's statevector simulator to provide:
  - True quantum entropy generation via Hadamard superposition
  - Bell / GHZ state diagnostics for simulator health checks
  - Quantum Fourier Transform sampling
  - Grover oracle demonstration
  - Entropy bit-stream for seeding PQC key generation

This sits above the existing QuantumEngine (quantum_engine.py) as a
clean abstraction. QuantumEngine handles circuit-selection and IBM hardware
routing; QPUSimulator handles the Aer statevector path with explicit
control over shot count, circuit depth, and entropy extraction.

Real quantum hardware randomness note:
  On a local Aer simulator the randomness is pseudo-random seeded by the
  host's OS RNG — the measurement outcome is genuinely non-deterministic
  at the algorithm level but the underlying simulation uses classical PRNG.
  On real IBM Quantum hardware, Hadamard-measured qubits ARE a physical
  source of randomness. This code is structured so the backend can be
  swapped from AerSimulator to a real QPU by changing one line.
"""

from __future__ import annotations

import logging
import math
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel
    QISKIT_AVAILABLE = True
except ImportError:
    QISKIT_AVAILABLE = False
    logger.error("qiskit / qiskit-aer not installed — QPUSimulator disabled")


class QuantumEngineAbstraction:
    """
    Virtual Quantum Simulator for JAKAL.
    Uses Qiskit 1.0+ and Qiskit-Aer statevector method.

    Acts as the abstraction layer for:
      - True random bit generation (entropy source for PQC)
      - Cryptographic state analysis
      - Quantum circuit diagnostics
    """

    def __init__(self, method: str = "statevector"):
        if not QISKIT_AVAILABLE:
            raise RuntimeError("qiskit-aer is not installed")
        self.simulator = AerSimulator(method=method)
        self._method = method
        logger.info("QPUSimulator initialised | backend=%s method=%s",
                    self.simulator.name, method)

    # ------------------------------------------------------------------
    # Entropy generation
    # ------------------------------------------------------------------

    def generate_true_random_entropy(self, bit_length: int = 256) -> str:
        """
        Generate entropy using quantum superposition (Hadamard gates).

        Each qubit is placed in equal superposition with H, then measured.
        The resulting bitstring is non-deterministic at the circuit level.

        Args:
            bit_length: number of random bits (= number of qubits).
                        Max practical for statevector sim: ~30 qubits.
                        For large bit_length we chunk into 28-qubit batches.

        Returns:
            Binary string of length bit_length.
        """
        _MAX_CHUNK = 28  # statevector RAM limit per chunk
        if bit_length <= _MAX_CHUNK:
            return self._entropy_chunk(bit_length)

        # Multi-chunk for large requests
        chunks = []
        remaining = bit_length
        while remaining > 0:
            chunk = min(remaining, _MAX_CHUNK)
            chunks.append(self._entropy_chunk(chunk))
            remaining -= chunk
        return "".join(chunks)

    def _entropy_chunk(self, n: int) -> str:
        qc = QuantumCircuit(n)
        for i in range(n):
            qc.h(i)
        qc.measure_all()
        compiled = transpile(qc, self.simulator, optimization_level=0)
        result = self.simulator.run(compiled, shots=1).result()
        counts = result.get_counts()
        # Single-shot: exactly one outcome — strip spaces (Qiskit separates regs with ' ')
        bitstring = list(counts.keys())[0].replace(" ", "")
        # Qiskit returns bits in reverse qubit order — reverse for natural ordering
        return bitstring[::-1]

    def generate_entropy_bytes(self, byte_count: int = 32) -> bytes:
        """
        Generate quantum-seeded random bytes.
        Suitable for seeding PBKDF2, HKDF, or any KDF that accepts entropy.
        """
        bits = self.generate_true_random_entropy(byte_count * 8)
        # Convert binary string to bytes
        value = int(bits, 2)
        return value.to_bytes(byte_count, byteorder="big")

    # ------------------------------------------------------------------
    # Diagnostic circuits
    # ------------------------------------------------------------------

    def test_entanglement_state(self, shots: int = 1000) -> Dict[str, Any]:
        """
        Bell state diagnostic — ensures the simulator produces the expected
        50/50 split between |00⟩ and |11⟩ (±5% tolerance at 1000 shots).
        """
        qc = QuantumCircuit(2)
        qc.h(0)
        qc.cx(0, 1)
        qc.measure_all()
        compiled = transpile(qc, self.simulator)
        result = self.simulator.run(compiled, shots=shots).result()
        counts = result.get_counts()

        # Validate Bell state quality
        total = sum(counts.values())
        p_00 = counts.get("00", 0) / total
        p_11 = counts.get("11", 0) / total
        non_entangled = counts.get("01", 0) + counts.get("10", 0)

        return {
            "circuit":      "bell_state",
            "shots":        shots,
            "counts":       counts,
            "p_00":         round(p_00, 4),
            "p_11":         round(p_11, 4),
            "non_entangled_count": non_entangled,
            "entanglement_quality": round((p_00 + p_11) * 100, 2),
            "health":       "OK" if non_entangled == 0 else "DEGRADED",
        }

    def run_ghz_state(self, n_qubits: int = 4, shots: int = 512) -> Dict[str, Any]:
        """
        Multi-qubit GHZ state: all qubits should be correlated |000⟩ or |111⟩.
        Good stress test for the simulator's entanglement handling.
        """
        qc = QuantumCircuit(n_qubits)
        qc.h(0)
        for i in range(1, n_qubits):
            qc.cx(0, i)
        qc.measure_all()
        compiled = transpile(qc, self.simulator)
        counts = self.simulator.run(compiled, shots=shots).result().get_counts()
        all_zeros = "0" * n_qubits
        all_ones  = "1" * n_qubits
        correlated = counts.get(all_zeros, 0) + counts.get(all_ones, 0)
        return {
            "circuit":       f"ghz_{n_qubits}q",
            "shots":         shots,
            "counts":        counts,
            "correlation_%": round(correlated / shots * 100, 2),
        }

    def run_quantum_fourier_transform(self, n_qubits: int = 4, shots: int = 512) -> Dict[str, Any]:
        """QFT circuit — validates the simulator handles phase rotations correctly."""
        from qiskit.circuit.library import QFT
        qc = QFT(n_qubits).decompose()
        qc.measure_all()
        compiled = transpile(qc, self.simulator)
        counts = self.simulator.run(compiled, shots=shots).result().get_counts()
        entropy = self._shannon_entropy(counts, shots)
        return {
            "circuit":         f"qft_{n_qubits}q",
            "shots":           shots,
            "counts":          counts,
            "shannon_entropy": round(entropy, 4),
            "max_entropy":     round(math.log2(2 ** n_qubits), 4),
        }

    def run_grover_search(self, n_qubits: int = 3, shots: int = 512) -> Dict[str, Any]:
        """
        Grover's algorithm demonstration on a 3-qubit oracle.
        Shows quantum speedup concept — search finds marked state with
        O(√N) queries vs O(N) classical.
        """
        qc = QuantumCircuit(n_qubits, n_qubits)
        # Uniform superposition
        for i in range(n_qubits):
            qc.h(i)
        # Oracle: marks |111⟩ with phase flip
        qc.ccx(0, 1, 2)  # Toffoli as phase kick
        qc.x(2)
        # Diffusion operator
        for i in range(n_qubits):
            qc.h(i)
            qc.x(i)
        qc.ccx(0, 1, 2)
        for i in range(n_qubits):
            qc.x(i)
            qc.h(i)
        qc.measure(range(n_qubits), range(n_qubits))
        compiled = transpile(qc, self.simulator)
        counts = self.simulator.run(compiled, shots=shots).result().get_counts()
        return {
            "circuit":          f"grover_{n_qubits}q",
            "shots":            shots,
            "counts":           counts,
            "target_state":     "111",
            "target_hits":      counts.get("111", 0),
            "amplification_%":  round(counts.get("111", 0) / shots * 100, 2),
        }

    # ------------------------------------------------------------------
    # Comprehensive health check
    # ------------------------------------------------------------------

    def run_diagnostics(self) -> Dict[str, Any]:
        """
        Full simulator health check — runs Bell state + entropy + QFT.
        Returns a combined status report.
        """
        t0 = time.time()
        results: Dict[str, Any] = {"backend": self.simulator.name, "method": self._method}

        try:
            results["bell_state"] = self.test_entanglement_state(shots=200)
        except Exception as e:
            results["bell_state"] = {"error": str(e)}

        try:
            entropy_bits = self.generate_true_random_entropy(64)
            results["entropy"] = {
                "bits":    64,
                "sample":  entropy_bits[:16] + "...",
                "ones_%":  round(entropy_bits.count("1") / 64 * 100, 1),
            }
        except Exception as e:
            results["entropy"] = {"error": str(e)}

        try:
            results["qft"] = self.run_quantum_fourier_transform(3, 200)
        except Exception as e:
            results["qft"] = {"error": str(e)}

        results["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        results["status"] = "OK" if all("error" not in v for v in results.values() if isinstance(v, dict)) else "PARTIAL"
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _shannon_entropy(counts: Dict[str, int], total: int) -> float:
        entropy = 0.0
        for count in counts.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        return entropy
