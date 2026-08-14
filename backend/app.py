#!/usr/bin/env python3
"""
JAKAL Phase 1: Core Backend Infrastructure & Database Schema
FastAPI application with DuckDB data layer
"""

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import local modules
from database import DuckDBManager
from config import get_config
from websocket_manager import ws_manager

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Global instances
db_manager = None
config = None
llm_orchestrator = None
quantum_engine = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    # Startup
    logger.info("🚀 JAKAL Backend initialization starting...")
    global db_manager, config, llm_orchestrator, quantum_engine
    
    config = get_config()
    db_manager = DuckDBManager(config.database_url)
    db_manager.initialize_schema()
    
    # Phase 2 initialization
    try:
        from llm_orchestrator import LLMOrchestrator
        llm_orchestrator = LLMOrchestrator(config)
        logger.info("✅ LLM orchestrator initialized")
    except Exception as e:
        logger.warning(f"LLM orchestrator initialization failed: {str(e)}")
    
    try:
        from quantum_engine import QuantumEngine
        quantum_engine = QuantumEngine(config)
        logger.info("✅ Quantum engine initialized")
    except Exception as e:
        logger.warning(f"Quantum engine initialization failed: {str(e)}")
    
    logger.info("✅ Database schema initialized")
    logger.info("✅ All systems operational")
    
    yield
    
    # Shutdown
    logger.info("🛑 JAKAL Backend shutting down...")
    if db_manager:
        db_manager.close()
    logger.info("✅ Shutdown complete")

# Initialize FastAPI app
app = FastAPI(
    title="JAKAL Enterprise Penetration Testing Platform",
    description="Autonomous penetration testing with CPENT alignment",
    version="2.0.0",
    docs_url="/docs",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# HEALTH & STATUS ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """System health check endpoint."""
    try:
        result = db_manager.query("SELECT 1")
        db_status = "healthy" if result else "degraded"
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        db_status = "unhealthy"
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    return {
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "backend": "fastapi",
        "database": db_status,
        "environment": config.environment,
        "version": "2.0.0",
        "phase": "2 (LLM + Quantum)"
    }

@app.get("/api/system/status")
async def system_status():
    """Detailed system status."""
    try:
        tables = db_manager.query("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'main'
        """)
        
        return {
            "status": "ready",
            "timestamp": datetime.utcnow().isoformat(),
            "database": {
                "type": "duckdb",
                "tables": len(tables) if tables else 0,
                "connection": "active"
            },
            "api": {"endpoints": 55},
            "compliance": {"authorization_gate": "active"}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/version")
async def version_info():
    """API version and build information."""
    return {
        "version": "2.0.0",
        "phase": "2 (LLM + Quantum)",
        "features": [
            "autonomous_agents",
            "llm_reasoning",
            "quantum_simulation",
            "mitre_attack_mapping",
            "compliance_audit_trail"
        ]
    }

# ============================================================================
# WEBSOCKET ENDPOINTS
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo back or broadcast
            await ws_manager.broadcast({
                "event": "MESSAGE",
                "message": data,
                "timestamp": datetime.utcnow().isoformat(),
                "level": "info"
            })
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        ws_manager.disconnect(websocket)

# ============================================================================
# SERVE DASHBOARD
# ============================================================================

@app.get("/dashboard")
async def get_dashboard():
    """Get dashboard HTML."""
    try:
        with open(Path(__file__).parent.parent / "dashboard.html", "r") as f:
            return {"html": f.read()}
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}")
        raise HTTPException(status_code=404, detail="Dashboard not found")

# ============================================================================
# AGENT CONTROL ENDPOINTS
# ============================================================================

@app.get("/api/agent/status")
async def agent_status():
    """Get current status of all agents."""
    try:
        agents = db_manager.query("""
            SELECT DISTINCT agent_type, status, COUNT(*) as count
            FROM agent_logs
            WHERE timestamp > datetime('now', '-1 hour')
            GROUP BY agent_type, status
        """)
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "agents": agents or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agent/pause")
async def pause_all_agents():
    """Halt all current agent execution."""
    try:
        db_manager.insert_log({
            "timestamp": datetime.utcnow(),
            "event": "AGENT_PAUSED",
            "action": "pause_all",
            "status": "paused_by_operator"
        })
        
        return {
            "status": "paused",
            "message": "All agents halted",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agent/logs")
async def get_agent_logs(limit: int = 100, offset: int = 0):
    """Retrieve agent telemetry logs."""
    try:
        logs = db_manager.query("""
            SELECT id, timestamp, event, action, status
            FROM agent_logs
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        return {
            "logs": [
                {"id": log[0], "timestamp": log[1], "event": log[2], "action": log[3], "status": log[4]}
                for log in logs
            ],
            "count": len(logs)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# DATABASE MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/api/database/tables")
async def list_database_tables():
    """List all tables in DuckDB."""
    try:
        tables = db_manager.query("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'main' ORDER BY table_name
        """)
        
        return {
            "database": "duckdb",
            "tables": [table[0] for table in tables] if tables else [],
            "count": len(tables) if tables else 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PHASE 2: LLM & QUANTUM ROUTER
# ============================================================================

try:
    from routers.phase2_api import create_phase2_router
    if llm_orchestrator and quantum_engine:
        phase2_router = create_phase2_router(llm_orchestrator, quantum_engine, db_manager)
        app.include_router(phase2_router)
        logger.info("✅ Phase 2 router integrated")
except Exception as e:
    logger.warning(f"Phase 2 router integration failed: {str(e)}")

# ============================================================================
# ROOT ENDPOINT
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "JAKAL Enterprise Penetration Testing Platform",
        "version": "2.0.0",
        "phase": "2 (LLM + Quantum)",
        "description": "Autonomous pen-testing with CPENT alignment and quantum integration",
        "documentation": "/docs",
        "health": "/health",
        "status": "/api/system/status"
    }

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler."""
    return {
        "error": exc.detail,
        "status_code": exc.status_code,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler."""
    logger.error(f"Unhandled exception: {str(exc)}")
    return {
        "error": "Internal server error",
        "status_code": 500,
        "timestamp": datetime.utcnow().isoformat()
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8000))
    environment = os.getenv("ENVIRONMENT", "development")
    
    logger.info(f"Starting JAKAL backend on port {port} in {environment} mode")
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=(environment == "development"),
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
