# PHASE 2 INTEGRATION GUIDE
## How to Update Your Backend for LLM & Quantum

**This guide updates your existing `backend/app.py` to include Phase 2 features.**

---

## Step 1: Copy Phase 2 Files

Copy these new files to your backend directory:

```
backend/
├── llm_orchestrator.py          ← phase2_llm_orchestrator.py
├── quantum_engine.py             ← phase2_quantum_engine.py
└── routers/
    └── phase2_api.py             ← phase2_api_router.py
```

---

## Step 2: Update requirements.txt

Add these lines to your `requirements.txt`:

```
# Phase 2: LLM & Quantum
google-generativeai==0.3.0
qiskit==0.43.3
qiskit-aer==0.13.1
qiskit-ibm-runtime==0.20.0
aiohttp==3.9.1
```

Install:
```bash
pip install -r requirements.txt
```

---

## Step 3: Update app.py

Modify your `backend/app.py` to add Phase 2 imports and initialization:

### Add imports at top of file:

```python
from backend.llm_orchestrator import LLMOrchestrator
from backend.quantum_engine import QuantumEngine
from backend.routers.phase2_api import create_phase2_router
```

### In your lifespan function, add after db_manager initialization:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 JAKAL Backend initialization starting...")
    global db_manager, config, llm_orchestrator, quantum_engine
    
    config = get_config()
    db_manager = DuckDBManager(config.database_url)
    db_manager.initialize_schema()
    
    # NEW: Initialize Phase 2 components
    llm_orchestrator = LLMOrchestrator(config)
    quantum_engine = QuantumEngine(config)
    
    logger.info("✅ Database schema initialized")
    logger.info("✅ LLM orchestrator initialized")
    logger.info("✅ Quantum engine initialized")
    logger.info("✅ All systems operational")
    
    yield
    
    # Shutdown
    logger.info("🛑 JAKAL Backend shutting down...")
    if db_manager:
        db_manager.close()
    logger.info("✅ Shutdown complete")
```

### Add global variables near top of file:

```python
# Global instances
db_manager = None
config = None
llm_orchestrator = None
quantum_engine = None
```

### Before the "if __name__ == __main__" section, add Phase 2 router:

```python
# ============================================================================
# PHASE 2: LLM & QUANTUM ROUTER
# ============================================================================

phase2_router = create_phase2_router(llm_orchestrator, quantum_engine, db_manager)
app.include_router(phase2_router)
```

---

## Step 4: Complete Updated app.py

Here's the complete minimal update needed:

```python
#!/usr/bin/env python3
"""
JAKAL Phase 1+2 Backend Application
FastAPI with LLM & Quantum Integration
"""

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import local modules
from database import DuckDBManager
from config import get_config
from llm_orchestrator import LLMOrchestrator  # NEW
from quantum_engine import QuantumEngine        # NEW
from routers.phase2_api import create_phase2_router  # NEW

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Global instances
db_manager = None
config = None
llm_orchestrator = None  # NEW
quantum_engine = None    # NEW

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    # Startup
    logger.info("🚀 JAKAL Backend initialization starting...")
    global db_manager, config, llm_orchestrator, quantum_engine
    
    config = get_config()
    db_manager = DuckDBManager(config.database_url)
    db_manager.initialize_schema()
    
    # NEW: Phase 2 initialization
    llm_orchestrator = LLMOrchestrator(config)
    quantum_engine = QuantumEngine(config)
    
    logger.info("✅ Database schema initialized")
    logger.info("✅ LLM orchestrator initialized")
    logger.info("✅ Quantum engine initialized")
    logger.info(f"📊 LLM providers: {llm_orchestrator.available_providers}")
    logger.info(f"⚛️  Quantum backends: {quantum_engine.health_check()}")
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
    description="Autonomous penetration testing with CPENT alignment, MITRE ATT&CK mapping, quantum integration",
    version="2.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
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
# EXISTING ENDPOINTS (Phase 1 & 1B)
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

# ... (Include all existing Phase 1 endpoints here) ...

# ============================================================================
# PHASE 2: LLM & QUANTUM ROUTER
# ============================================================================

phase2_router = create_phase2_router(llm_orchestrator, quantum_engine, db_manager)
app.include_router(phase2_router)

# ============================================================================
# ROOT
# ============================================================================

@app.get("/")
async def root():
    """API information."""
    return {
        "name": "JAKAL Enterprise Penetration Testing Platform",
        "version": "2.0.0",
        "phase": "2 (LLM + Quantum Integration)",
        "features": [
            "autonomous_agents",
            "llm_reasoning",
            "quantum_simulation",
            "quantum_resistant_encryption_analysis",
            "mitre_attack_mapping",
            "compliance_audit_trail"
        ]
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8000))
    environment = os.getenv("ENVIRONMENT", "development")
    
    logger.info(f"Starting JAKAL backend (Phase 2) on port {port} in {environment} mode")
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=(environment == "development"),
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
```

---

## Step 5: Create routers directory

```bash
mkdir -p backend/routers
touch backend/routers/__init__.py
```

Move phase2_api_router.py to backend/routers/phase2_api.py

---

## Step 6: Test Phase 2 Endpoints Locally

Start your backend:

```bash
cd backend
python app.py
```

Test endpoints:

```bash
# Test LLM health
curl http://localhost:8000/api/llm/health

# Test Quantum health
curl http://localhost:8000/api/quantum/health

# Run Bell State circuit
curl -X POST http://localhost:8000/api/quantum/bell-state \
  -H "Content-Type: application/json" \
  -d '{"shots": 1024}'

# Analyze OSINT results
curl -X POST http://localhost:8000/api/llm/analyze/osint \
  -H "Content-Type: application/json" \
  -d '{
    "target": "example.com",
    "dns_records": {"A": "1.2.3.4"},
    "ssl_cert": "valid"
  }'

# Get PQC readiness
curl http://localhost:8000/api/quantum/pqc-readiness

# View all endpoints
# Open: http://localhost:8000/docs
```

---

## New Phase 2 Endpoints (30+)

### LLM Endpoints (5)
- `GET /api/llm/health` - Check LLM providers
- `POST /api/llm/analyze/osint` - Analyze reconnaissance
- `POST /api/llm/analyze/scan` - Analyze network scan
- `POST /api/llm/strategy/exploitation` - Recommend exploit strategy
- `POST /api/llm/report/executive-summary` - Generate report summary

### MITRE ATT&CK Endpoints (3)
- `POST /api/mitre/map-findings` - Map findings to MITRE
- `GET /api/mitre/tactic/{tactic_name}` - Get tactic description
- `GET /api/mitre/technique/{technique_id}` - Get technique info

### Quantum Endpoints (8)
- `GET /api/quantum/health` - Check quantum engine
- `POST /api/quantum/bell-state` - Run Bell State circuit
- `POST /api/quantum/grover-search` - Run Grover's algorithm
- `POST /api/quantum/qaoa-optimization` - Run QAOA
- `GET /api/quantum/brute-force-cost/{key_size}` - Estimate brute-force cost
- `GET /api/quantum/pqc-readiness` - Quantum-resistant encryption readiness
- `GET /api/quantum/jobs` - List quantum jobs
- `GET /api/quantum/jobs/{job_id}` - Get job result

---

## Testing Checklist

```
✅ Backend starts without errors
✅ /health endpoint responds with Phase 2 info
✅ /api/llm/health returns provider status
✅ /api/quantum/health returns quantum status
✅ /api/quantum/bell-state executes circuit
✅ /api/llm/analyze/osint processes data
✅ /api/mitre/map-findings correlates findings
✅ /api/quantum/pqc-readiness returns recommendations
✅ All endpoints logged to agent_logs
✅ API docs show 40+ endpoints at /docs
```

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'qiskit'"
```bash
pip install qiskit qiskit-aer qiskit-ibm-runtime
```

### "Gemini API key not set"
- Fill GEMINI_API_KEY in .env
- Restart backend

### "Quantum features unavailable"
- Qiskit is optional - backend works without it
- Check logs for import errors
- Install with: `pip install qiskit`

### "AttributeError: 'NoneType' object"
- Make sure llm_orchestrator and quantum_engine are initialized in lifespan()
- Check startup logs for initialization messages

---

## Next: Proceed to Phase 2B (GACyber Tool Kit)

After Phase 2 is working locally:
1. Deploy to Oracle Cloud
2. Request Phase 2B code (GaCyber Tool Kit)
3. Then Phase 3 (Security Agents)

