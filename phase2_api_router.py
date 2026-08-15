#!/usr/bin/env python3
"""
JAKAL Phase 2: API Integration Module
FastAPI endpoints for LLM and Quantum features
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def create_phase2_router(llm_orchestrator, quantum_engine, db_manager):
    """Create Phase 2 API endpoints router."""
    router = APIRouter(prefix="/api", tags=["Phase 2: LLM & Quantum"])
    
    # ========================================================================
    # LLM ENDPOINTS
    # ========================================================================
    
    @router.get("/llm/health")
    async def llm_health():
        """Check LLM providers health."""
        health = llm_orchestrator.health_check()
        return {
            "llm_health": health,
            "providers": llm_orchestrator.available_providers,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @router.post("/llm/analyze/osint")
    async def analyze_osint(osint_data: Dict[str, Any]):
        """Analyze OSINT reconnaissance results."""
        try:
            analysis = await llm_orchestrator.analyze_osint_results(osint_data)
            
            # Log to database
            db_manager.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "LLM_OSINT_ANALYSIS",
                "action": "analyze_osint",
                "status": "completed",
                "details": {"target": osint_data.get("target")}
            })
            
            return analysis
        except Exception as e:
            logger.error(f"OSINT analysis failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/llm/analyze/scan")
    async def analyze_scan(scan_data: Dict[str, Any]):
        """Analyze network scan results."""
        try:
            analysis = await llm_orchestrator.analyze_scan_results(scan_data)
            
            db_manager.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "LLM_SCAN_ANALYSIS",
                "action": "analyze_scan",
                "status": "completed",
                "details": {"target": scan_data.get("target")}
            })
            
            return analysis
        except Exception as e:
            logger.error(f"Scan analysis failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/llm/strategy/exploitation")
    async def recommend_exploitation(findings: List[Dict[str, Any]]):
        """Recommend exploitation strategy based on findings."""
        try:
            strategy = await llm_orchestrator.recommend_exploitation_strategy(findings)
            
            db_manager.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "LLM_STRATEGY_RECOMMENDATION",
                "action": "recommend_exploitation",
                "status": "completed",
                "details": {"finding_count": len(findings)}
            })
            
            return strategy
        except Exception as e:
            logger.error(f"Strategy recommendation failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/llm/report/executive-summary")
    async def generate_executive_summary(findings: List[Dict], pentest_data: Dict):
        """Generate executive summary for assessment report."""
        try:
            summary = await llm_orchestrator.generate_assessment_summary(findings, pentest_data)
            
            db_manager.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "LLM_SUMMARY_GENERATION",
                "action": "generate_summary",
                "status": "completed"
            })
            
            return {"summary": summary}
        except Exception as e:
            logger.error(f"Summary generation failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # ========================================================================
    # MITRE ATT&CK ENDPOINTS
    # ========================================================================
    
    @router.post("/mitre/map-findings")
    async def map_findings_to_mitre(findings: List[Dict[str, Any]]):
        """Map findings to MITRE ATT&CK framework."""
        try:
            mappings = llm_orchestrator.map_to_mitre_attack(findings)
            
            db_manager.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "MITRE_MAPPING",
                "action": "map_findings",
                "status": "completed",
                "details": {"finding_count": len(findings)}
            })
            
            return mappings
        except Exception as e:
            logger.error(f"MITRE mapping failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/mitre/tactic/{tactic_name}")
    async def get_tactic_description(tactic_name: str):
        """Get description of MITRE tactic."""
        return {
            "tactic": tactic_name,
            "description": llm_orchestrator.get_mitre_tactic_description(tactic_name)
        }
    
    @router.get("/mitre/technique/{technique_id}")
    async def get_technique_info(technique_id: str):
        """Get detailed info about MITRE technique."""
        info = llm_orchestrator.get_technique_info(technique_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"Technique {technique_id} not found")
        return {"technique_id": technique_id, "info": info}
    
    # ========================================================================
    # QUANTUM ENDPOINTS
    # ========================================================================
    
    @router.get("/quantum/health")
    async def quantum_health():
        """Check quantum engine health."""
        health = quantum_engine.health_check()
        return {
            "quantum_health": health,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @router.post("/quantum/bell-state")
    async def run_bell_state(shots: int = 1024):
        """Run Bell State circuit (quantum entanglement test)."""
        try:
            result = quantum_engine.run_bell_state(shots=shots)
            
            db_manager.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "QUANTUM_BELL_STATE",
                "action": "run_circuit",
                "status": "completed",
                "details": {"shots": shots}
            })
            
            return result
        except Exception as e:
            logger.error(f"Bell state execution failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/quantum/grover-search")
    async def run_grover(marked_elements: List[int], total_elements: int = 8, shots: int = 1024):
        """Run Grover's algorithm (quantum search)."""
        try:
            result = quantum_engine.run_grover_search(marked_elements, total_elements, shots)
            
            db_manager.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "QUANTUM_GROVER_SEARCH",
                "action": "run_circuit",
                "status": "completed",
                "details": {"marked_count": len(marked_elements)}
            })
            
            return result
        except Exception as e:
            logger.error(f"Grover search failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/quantum/qaoa-optimization")
    async def run_qaoa(problem_size: int = 4, shots: int = 1024):
        """Run QAOA (quantum optimization)."""
        try:
            result = quantum_engine.run_qaoa_optimization(problem_size, shots)
            
            db_manager.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "QUANTUM_QAOA",
                "action": "run_circuit",
                "status": "completed",
                "details": {"problem_size": problem_size}
            })
            
            return result
        except Exception as e:
            logger.error(f"QAOA execution failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/quantum/brute-force-cost/{key_size}")
    async def estimate_brute_force(key_size: int):
        """Estimate classical vs quantum brute-force cost."""
        if key_size < 8 or key_size > 256:
            raise HTTPException(status_code=400, detail="Key size must be between 8 and 256")
        
        return quantum_engine.estimate_classical_brute_force_cost(key_size)
    
    @router.get("/quantum/pqc-readiness")
    async def quantum_resistant_encryption():
        """Evaluate quantum-resistant encryption readiness."""
        return quantum_engine.evaluate_quantum_resistant_encryption()
    
    @router.get("/quantum/jobs")
    async def list_quantum_jobs(limit: int = 10):
        """List recent quantum job results."""
        jobs = quantum_engine.list_jobs(limit)
        return {
            "jobs": jobs,
            "count": len(jobs),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @router.get("/quantum/jobs/{job_id}")
    async def get_quantum_job(job_id: str):
        """Retrieve specific quantum job result."""
        result = quantum_engine.get_job_result(job_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return result
    
    return router
