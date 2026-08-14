#!/usr/bin/env python3
"""JAKAL Phase 2: API Router - LLM & Quantum Endpoints"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def create_phase2_router(llm_orchestrator, quantum_engine, db_manager):
    """Create Phase 2 API endpoints router."""
    router = APIRouter(prefix="/api", tags=["Phase 2: LLM & Quantum"])
    
    @router.get("/llm/health")
    async def llm_health():
        """Check LLM providers health."""
        return {
            "llm_health": llm_orchestrator.health_check(),
            "providers": llm_orchestrator.available_providers,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @router.post("/llm/analyze/osint")
    async def analyze_osint(osint_data: Dict[str, Any]):
        """Analyze OSINT reconnaissance results."""
        try:
            analysis = await llm_orchestrator.analyze_osint_results(osint_data)
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
            raise HTTPException(status_code=500, detail=str(e))
    
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
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/quantum/health")
    async def quantum_health():
        """Check quantum engine health."""
        return {
            "quantum_health": quantum_engine.health_check(),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @router.post("/quantum/bell-state")
    async def run_bell_state(shots: int = 1024):
        """Run Bell State circuit."""
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
            raise HTTPException(status_code=500, detail=str(e))
    
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
    
    return router
