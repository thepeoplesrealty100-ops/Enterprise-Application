#!/usr/bin/env python3
"""
JAKAL Phase 2: Quantum Engine
Qiskit-Aer local simulator + IBM Quantum hardware integration
"""

import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import numpy as np

try:
    from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
    from qiskit_aer import AerSimulator
    from qiskit_aer.primitives import Sampler, Estimator
    QISKIT_AVAILABLE = True
except ImportError:
    QISKIT_AVAILABLE = False
    logging.warning("Qiskit not available - quantum features disabled")

try:
    from qiskit_ibm_runtime import QiskitRuntimeService
    IBM_QUANTUM_AVAILABLE = True
except ImportError:
    IBM_QUANTUM_AVAILABLE = False
    logging.warning("IBM Quantum Runtime not available")

logger = logging.getLogger(__name__)

class QuantumEngine:
    """
    Quantum circuit execution engine.
    Primary: Qiskit-Aer local simulator (unlimited)
    Optional: IBM Quantum hardware (10 min/month free)
    """
    
    def __init__(self, config):
        self.config = config
        self.qiskit_available = QISKIT_AVAILABLE
        self.ibm_available = False
        self.job_results = {}
        
        if not self.qiskit_available:
            logger.warning("Qiskit not installed - quantum features unavailable")
            return
        
        # Initialize Qiskit Aer simulator
        try:
            self.simulator = AerSimulator()
            self.sampler = Sampler()
            self.estimator = Estimator()
            logger.info("✅ Qiskit-Aer simulator initialized")
        except Exception as e:
            logger.error(f"Qiskit initialization failed: {str(e)}")
            self.qiskit_available = False
        
        # Try to initialize IBM Quantum
        if config.ibm_quantum_token and IBM_QUANTUM_AVAILABLE:
            try:
                self._initialize_ibm_quantum()
            except Exception as e:
                logger.warning(f"IBM Quantum initialization failed: {str(e)}")
    
    def _initialize_ibm_quantum(self) -> None:
        """Initialize IBM Quantum service."""
        try:
            QiskitRuntimeService.save_account(
                channel="ibm_quantum",
                instance=self.config.ibm_quantum_instance,
                token=self.config.ibm_quantum_token,
                overwrite=True
            )
            
            self.ibm_service = QiskitRuntimeService()
            self.ibm_available = True
            logger.info("✅ IBM Quantum Open Plan initialized")
        except Exception as e:
            logger.warning(f"IBM Quantum setup failed: {str(e)}")
            self.ibm_available = False
    
    def run_bell_state(self, shots: int = 1024, backend: str = "local") -> Dict[str, Any]:
        """
        Run Bell State circuit (tests quantum entanglement).
        Useful for verifying quantum capability and infrastructure.
        """
        if not self.qiskit_available:
            return {"error": "Qiskit not available"}
        
        try:
            # Create Bell State circuit
            qc = QuantumCircuit(2, 2, name="Bell State")
            qc.h(0)  # Hadamard on first qubit
            qc.cx(0, 1)  # CNOT (entangle)
            qc.measure([0, 1], [0, 1])  # Measure both qubits
            
            return self._execute_circuit(qc, shots, backend)
        except Exception as e:
            logger.error(f"Bell state execution failed: {str(e)}")
            return {"error": str(e)}
    
    def run_grover_search(self, marked_elements: List[int], total_elements: int = 8, 
                         shots: int = 1024) -> Dict[str, Any]:
        """
        Run Grover's algorithm (quantum search).
        Demonstrates quadratic speedup for database search.
        Useful for brute-force cost analysis.
        """
        if not self.qiskit_available:
            return {"error": "Qiskit not available"}
        
        try:
            n_qubits = len(bin(total_elements - 1)) - 2
            qc = QuantumCircuit(n_qubits, n_qubits, name=f"Grover (search {marked_elements})")
            
            # Initialize superposition
            qc.h(range(n_qubits))
            
            # Oracle: mark the search targets
            for marked in marked_elements:
                binary = format(marked, f'0{n_qubits}b')
                for i, bit in enumerate(binary):
                    if bit == '0':
                        qc.x(i)
                if n_qubits > 1:
                    qc.mz(list(range(n_qubits - 1)), n_qubits - 1)
                for i, bit in enumerate(binary):
                    if bit == '0':
                        qc.x(i)
            
            # Diffusion operator
            qc.h(range(n_qubits))
            qc.x(range(n_qubits))
            qc.h(n_qubits - 1)
            if n_qubits > 1:
                qc.mz(list(range(n_qubits - 1)), n_qubits - 1)
            qc.h(n_qubits - 1)
            qc.x(range(n_qubits))
            qc.h(range(n_qubits))
            
            # Measure
            qc.measure(range(n_qubits), range(n_qubits))
            
            return self._execute_circuit(qc, shots)
        except Exception as e:
            logger.error(f"Grover search failed: {str(e)}")
            return {"error": str(e)}
    
    def run_qaoa_optimization(self, problem_size: int = 4, shots: int = 1024) -> Dict[str, Any]:
        """
        Run QAOA (Quantum Approximate Optimization Algorithm).
        Demonstrates quantum optimization for NP-hard problems.
        """
        if not self.qiskit_available:
            return {"error": "Qiskit not available"}
        
        try:
            # Simplified QAOA for MaxCut problem
            qc = QuantumCircuit(problem_size, problem_size, name=f"QAOA (p=1, size={problem_size})")
            
            # Initial superposition
            qc.h(range(problem_size))
            
            # Problem Hamiltonian: circular MaxCut
            for i in range(problem_size):
                for j in range(i + 1, min(i + 3, problem_size)):
                    qc.rzz(0.5, i, j)
            
            # Mixer Hamiltonian
            for i in range(problem_size):
                qc.rx(0.5, i)
            
            # Measure
            qc.measure(range(problem_size), range(problem_size))
            
            return self._execute_circuit(qc, shots)
        except Exception as e:
            logger.error(f"QAOA optimization failed: {str(e)}")
            return {"error": str(e)}
    
    def estimate_classical_brute_force_cost(self, key_size: int, quantum_advantage: bool = True) -> Dict[str, Any]:
        """
        Estimate computational cost of classical vs quantum brute force.
        Illustrates quantum advantage for cryptanalysis.
        """
        try:
            # Classical: 2^n operations (worst case average is 2^(n-1))
            classical_operations = 2 ** (key_size - 1)
            classical_time_seconds = classical_operations / 1e9  # At 1 GHz
            classical_time_years = classical_time_seconds / (365.25 * 24 * 3600)
            
            # Quantum (Grover): ~sqrt(2^n) = 2^(n/2) operations
            quantum_operations = 2 ** (key_size / 2) if quantum_advantage else classical_operations
            quantum_time_seconds = quantum_operations / 1e9
            quantum_time_years = quantum_time_seconds / (365.25 * 24 * 3600)
            
            # Speedup
            speedup = classical_operations / quantum_operations
            
            return {
                "key_size_bits": key_size,
                "classical": {
                    "operations": int(classical_operations),
                    "time_seconds": classical_time_seconds,
                    "time_years": classical_time_years,
                    "human_readable": self._format_large_time(classical_time_years)
                },
                "quantum_grover": {
                    "operations": int(quantum_operations),
                    "time_seconds": quantum_time_seconds,
                    "time_years": quantum_time_years,
                    "human_readable": self._format_large_time(quantum_time_years)
                },
                "quantum_advantage": {
                    "speedup_factor": speedup,
                    "breakthrough_possible": speedup > 1e9,
                    "practical_implication": "Quantum computing would break this encryption" if speedup > 1e9 else "Classical methods still viable"
                }
            }
        except Exception as e:
            logger.error(f"Cost estimation failed: {str(e)}")
            return {"error": str(e)}
    
    def evaluate_quantum_resistant_encryption(self) -> Dict[str, Any]:
        """
        Evaluate quantum-resistant encryption readiness.
        Assesses NIST PQC candidates and migration strategies.
        """
        try:
            pqc_algorithms = {
                "lattice_based": {
                    "name": "Lattice-Based (CRYSTALLINE, KYBER, DILITHIUM)",
                    "security_level": "HIGH",
                    "quantum_resistant": True,
                    "deployment_readiness": "2024-2025",
                    "nist_status": "Finalist"
                },
                "code_based": {
                    "name": "Code-Based (Classic McEliece)",
                    "security_level": "HIGH",
                    "quantum_resistant": True,
                    "deployment_readiness": "2025+",
                    "nist_status": "Alternate"
                },
                "multivariate": {
                    "name": "Multivariate (Rainbow)",
                    "security_level": "MEDIUM",
                    "quantum_resistant": True,
                    "deployment_readiness": "2025+",
                    "nist_status": "Under Review"
                },
                "hash_based": {
                    "name": "Hash-Based (SPHINCS)",
                    "security_level": "HIGH",
                    "quantum_resistant": True,
                    "deployment_readiness": "2024+",
                    "nist_status": "Approved"
                }
            }
            
            return {
                "pqc_candidates": pqc_algorithms,
                "recommendation": "Implement lattice-based encryption (KYBER) by 2025",
                "migration_plan": [
                    "Inventory all cryptographic systems",
                    "Identify quantum-critical data",
                    "Begin hybrid encryption (classical + PQC) pilots in 2024",
                    "Full PQC migration by 2026",
                    "Monitor NIST standardization progress"
                ],
                "immediate_actions": [
                    "Disable legacy encryption (RC4, DES, SHA-1)",
                    "Implement TLS 1.3",
                    "Deploy hardware security modules (HSMs)",
                    "Enable perfect forward secrecy (PFS)"
                ]
            }
        except Exception as e:
            logger.error(f"Quantum resistance evaluation failed: {str(e)}")
            return {"error": str(e)}
    
    def _execute_circuit(self, circuit: QuantumCircuit, shots: int = 1024, 
                        backend: str = "local") -> Dict[str, Any]:
        """Execute a quantum circuit on specified backend."""
        if not self.qiskit_available:
            return {"error": "Qiskit not available"}
        
        try:
            start_time = datetime.utcnow()
            
            # Transpile for simulator
            transpiled = transpile(circuit, self.simulator)
            
            # Run on local simulator
            job = self.simulator.run(transpiled, shots=shots)
            result = job.result()
            counts = result.get_counts()
            
            end_time = datetime.utcnow()
            execution_time = (end_time - start_time).total_seconds()
            
            # Store result
            job_id = f"job_{len(self.job_results) + 1}"
            self.job_results[job_id] = {
                "circuit": circuit.name,
                "counts": counts,
                "timestamp": start_time.isoformat()
            }
            
            # Calculate statistics
            max_count = max(counts.values())
            max_bitstring = [k for k, v in counts.items() if v == max_count][0]
            
            return {
                "job_id": job_id,
                "circuit_name": circuit.name,
                "shots": shots,
                "backend": "qiskit-aer",
                "execution_time_seconds": execution_time,
                "results": {
                    "counts": counts,
                    "max_count": max_count,
                    "max_bitstring": max_bitstring,
                    "probabilities": {k: v/shots for k, v in counts.items()}
                },
                "status": "COMPLETED"
            }
        except Exception as e:
            logger.error(f"Circuit execution failed: {str(e)}")
            return {"error": str(e)}
    
    def _format_large_time(self, years: float) -> str:
        """Format very large time values in human-readable form."""
        if years < 1:
            seconds = years * 365.25 * 24 * 3600
            if seconds < 60:
                return f"{seconds:.2e} seconds"
            elif seconds < 3600:
                return f"{seconds/60:.2e} minutes"
            else:
                return f"{seconds/3600:.2e} hours"
        elif years < 1e6:
            return f"{years:.2e} years"
        elif years < 1e15:
            return f"{years/1e9:.2e} billion years"
        else:
            return f"{years/1e15:.2e} trillion years"
    
    def get_job_result(self, job_id: str) -> Optional[Dict]:
        """Retrieve stored job result."""
        return self.job_results.get(job_id)
    
    def list_jobs(self, limit: int = 10) -> List[Dict]:
        """List recent job results."""
        return list(self.job_results.values())[-limit:]
    
    def health_check(self) -> Dict[str, Any]:
        """Check quantum engine health."""
        return {
            "qiskit_available": self.qiskit_available,
            "simulator_available": self.qiskit_available,
            "ibm_quantum_available": self.ibm_available,
            "job_count": len(self.job_results),
            "overall": self.qiskit_available
        }
