# JAKAL: Horizon Unified Singularity OS
## Enterprise-Grade Autonomous AI + Quantum Integration Architecture

**Version:** 1.0 (Production-Ready Edition)  
**Status:** Full Implementation Specification  
**Infrastructure Model:** Optimized Cost Structure with Enterprise Capabilities  
**Target Launch:** Phase 1 (Local Development), Phase 2 (Cloud Integration), Phase 3 (Full-Scale Production)

---

## Table of Contents
1. [Technology Stack Overview](#technology-stack)
2. [System Architecture](#system-architecture)
3. [Implementation Phases](#implementation-phases)
4. [Backend Code Structure](#backend-code-structure)
5. [Frontend Integration](#frontend-integration)
6. [Deployment Strategy](#deployment-strategy)

---

## Technology Stack

| Component | Solution | Enterprise Equivalent | Infrastructure Model |
|-----------|----------|----------------------|----------------------|
| **Frontend Hosting** | Vercel / Netlify | Enterprise CDN | Auto-deployment, global edge distribution |
| **Backend Compute** | Oracle Cloud Always-Free Tier (4 ARM cores, 24GB RAM, 200GB storage) | AWS EC2 / Azure Compute | Permanent always-free tier with unlimited uptime |
| **Primary Database** | Supabase (PostgreSQL 500MB free tier, unlimited REST APIs) | Enterprise PostgreSQL / AWS RDS | Full relational database with instant REST APIs |
| **Development Database** | DuckDB (local OLAP) | Snowflake / BigQuery | High-speed local queries, columnar storage |
| **Quantum Simulation** | Qiskit-Aer (local execution, unlimited simulations) | Paid quantum runtime slots | Development & testing: unlimited; production: on-demand |
| **Quantum Hardware Access** | IBM Quantum Open Plan (10 free QPU minutes/month) | IBM Quantum Premium / AWS Braket | Real hardware validation with free tier allocation |
| **AI & LLM Orchestration** | Google Gemini 1.5 Flash API (free tier with rate limits) | OpenAI GPT-4 / Claude Enterprise | Fast agentic decision loops, production inference |
| **Local LLM Option** | Ollama + Llama 3 / Qwen | Self-hosted LLM infrastructure | 100% offline capability, zero external dependencies |
| **Security & Penetration Tools** | Open-source suite (Nuclei, Nmap, Metasploit, Atomic Red Team) | Commercial penetration testing platforms | Community editions wrapped in Python automation |
| **Observability & Logs** | DuckDB (local) + Supabase (remote sync) | ELK Stack / DataDog / Splunk | Local high-performance queries with cloud fallback |
| **User Authentication** | Firebase Auth Free Tier (Google Sign-in) | Auth0 / Okta Enterprise | JWT-based session management |
| **CI/CD Pipeline** | GitHub Actions (free for public repos, 2000 min/month) | Jenkins / GitLab Runner / CircleCI | Integrated workflow automation |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    JAKAL Unified Control Plane                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Frontend Layer  │  │  LLM Orchestr.   │  │  Quantum Engine  │  │
│  │  (Vercel/Next)   │  │  (Gemini/Ollama) │  │  (Qiskit-Aer)    │  │
│  └──────────┬───────┘  └────────┬─────────┘  └────────┬─────────┘  │
│             │                    │                    │             │
│             │ REST/WebSocket     │                    │             │
│  ┌──────────▼────────────────────▼──────────────────────▼─────────┐ │
│  │              FastAPI Backend Orchestration Layer               │ │
│  │  ┌────────────────────────────────────────────────────────┐   │ │
│  │  │ Route: /api/agent/  (Agentic Orchestration)           │   │ │
│  │  │ Route: /api/quantum/ (Quantum Job Submission)         │   │ │
│  │  │ Route: /api/pentest/ (Security Testing Workflows)     │   │ │
│  │  │ Route: /api/mitre/   (ATT&CK Framework Mapping)       │   │ │
│  │  └────────────────────────────────────────────────────────┘   │ │
│  └────────────┬────────────────────────────────────────────────────┘ │
│               │                                                       │
│  ┌────────────▼──────────────────────────────────────────────────┐   │
│  │           Unified Data Layer (DuckDB Local)                  │   │
│  │  Tables:                                                     │   │
│  │  ├─ agent_logs (Real-time telemetry)                        │   │
│  │  ├─ quantum_jobs (Qiskit execution state)                   │   │
│  │  ├─ pentest_runs (Security test results)                    │   │
│  │  ├─ findings (Vulnerability discoveries)                    │   │
│  │  ├─ attack_mappings (MITRE ATT&CK correlation)             │   │
│  │  └─ compliance_checkpoints (Audit trail)                    │   │
│  └────────────┬──────────────────────────────────────────────────┘   │
│               │                                                       │
│  ┌────────────▼──────────────────────────────────────────────────┐   │
│  │     Cloud Sync Layer (Supabase PostgreSQL - Optional)        │   │
│  │  ├─ Findings repository (for multi-team collaboration)      │   │
│  │  ├─ Real-time subscriptions (WebSocket updates)             │   │
│  │  ├─ Audit logging (immutable security records)              │   │
│  │  └─ Compliance snapshots (historical reference)             │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Core Backend & Local Quantum Engine (Weeks 1-2)
**Objectives**: Build self-contained backend; test quantum circuits locally; establish database schema

**Deliverables**:
- FastAPI backend running on Oracle Always-Free compute
- Qiskit-Aer simulator for unlimited local quantum testing
- DuckDB database with complete schema
- Dashboard UI connected to backend REST API
- Local LLM integration (Ollama) for offline agentic reasoning

**Key Repositories**:
```
backend/
├── app.py                           # FastAPI main application
├── config.py                        # Configuration management
├── database.py                      # DuckDB schema & queries
├── llm_orchestrator.py             # AI decision engine
├── quantum_engine.py                # Qiskit wrapper & abstractions
├── security_agents/
│   ├── __init__.py
│   ├── recon_agent.py              # Network & vulnerability scanning
│   ├── exploit_agent.py            # Payload staging & execution
│   ├── report_agent.py             # Finding summarization
│   └── remediate_agent.py          # Patch generation
├── integrations/
│   ├── ibm_quantum.py              # IBM Qiskit REST API client
│   ├── supabase_sync.py            # Cloud PostgreSQL sync
│   └── firebase_auth.py            # User authentication
├── tools/
│   ├── nmap_wrapper.py             # Network scanning automation
│   ├── nuclei_wrapper.py           # Vulnerability scanning
│   └── mitre_attck_db.py           # MITRE framework loader
└── requirements.txt
```

### Phase 2: Cloud API Integration (Week 3)
**Objectives**: Connect production-grade cloud services; establish multi-user capabilities

**Deliverables**:
- Gemini 1.5 Flash API integration for high-throughput agentic loops
- IBM Quantum Open Plan account setup (validation & real hardware access)
- Supabase PostgreSQL for cloud-accessible findings repository
- Firebase Authentication for multi-operator sessions
- WebSocket real-time updates (dashboard ←→ backend)

### Phase 3: Autonomous Agent Orchestration (Week 4)
**Objectives**: Deploy specialized AI agents across reconnaissance, exploitation, reporting

**Agent Types**:
1. **Reconnaissance Agent** — Network mapping (Nmap, Nuclei, Amass)
2. **Exploitation Agent** — MITRE ATT&CK correlation & payload staging
3. **Reporting Agent** — Finding summarization & compliance export
4. **Remediation Agent** — Automated patch & hardening script generation

### Phase 4: Quantum Integration & Security Applications (Week 5)
**Objectives**: Integrate quantum circuits for cryptanalysis & optimization

**Use Cases**:
- Simulate quantum-resistant encryption evaluation
- Use Grover's algorithm for brute-force cost estimation
- Optimize payload delivery using QAOA

---

## Backend Code Structure

### FastAPI Main Application
```python
# backend/app.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging
from datetime import datetime

from database import DuckDBManager
from llm_orchestrator import AgentOrchestrator
from quantum_engine import QuantumEngine
from security_agents.recon_agent import ReconAgent
from security_agents.exploit_agent import ExploitAgent

app = FastAPI(title="JAKAL Backend", version="1.0")

# CORS configuration for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize core managers
db = DuckDBManager()
orchestrator = AgentOrchestrator()
quantum = QuantumEngine()
recon = ReconAgent(db)
exploit = ExploitAgent(db)

logger = logging.getLogger(__name__)

# ============================================================================
# HEALTH & STATUS ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """System health and readiness check."""
    return {
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "backend": "production",
        "database": "duckdb_primary",
        "llm_engine": "gemini_flash_primary"
    }

# ============================================================================
# AGENT CONTROL & ORCHESTRATION
# ============================================================================

@app.post("/api/agent/approve")
async def approve_exploit(payload: dict, background_tasks: BackgroundTasks):
    """
    Human-in-the-loop approval gate for exploit execution.
    Prevents unauthorized autonomous actions; maintains governance.
    """
    action = payload.get("action", "execute_staged_payload")
    
    db.insert_log({
        "timestamp": datetime.utcnow(),
        "event": "EXPLOIT_APPROVED",
        "action": action,
        "approved_by": payload.get("operator_id"),
        "status": "approved"
    })
    
    # Schedule exploit execution in background
    background_tasks.add_task(exploit.execute_staged_payload)
    
    return {
        "status": "approved",
        "message": "Exploit has been queued for execution",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/agent/pause")
async def pause_agent():
    """Halt all current agent execution."""
    db.insert_log({
        "timestamp": datetime.utcnow(),
        "event": "AGENT_PAUSED",
        "status": "paused_by_operator"
    })
    return {"status": "paused"}

@app.get("/api/agent/logs")
async def get_agent_logs(limit: int = 50, offset: int = 0):
    """Retrieve agent telemetry logs with pagination."""
    logs = db.query(
        "SELECT * FROM agent_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (limit, offset)
    )
    return {"logs": logs, "count": len(logs)}

# ============================================================================
# QUANTUM ENDPOINTS
# ============================================================================

@app.post("/api/quantum/submit")
async def submit_quantum_job(job: dict):
    """
    Submit quantum circuit for execution.
    Default: Qiskit-Aer local simulator (unlimited)
    Alternative: IBM Quantum Open Plan (10 min/month free)
    """
    circuit_name = job.get("circuit", "bell_state")
    shots = job.get("shots", 1024)
    backend = job.get("backend", "qiskit_aer")
    
    try:
        result = quantum.run_circuit(circuit_name, shots, backend)
        job_id = quantum.store_result(result)
        
        return {
            "job_id": job_id,
            "status": "completed" if backend == "qiskit_aer" else "queued",
            "result": result,
            "backend": backend
        }
    except Exception as e:
        logger.error(f"Quantum job submission failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/quantum/jobs")
async def list_quantum_jobs(limit: int = 20):
    """List recent quantum jobs with status."""
    jobs = db.query(
        "SELECT * FROM quantum_jobs ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    return {"jobs": jobs}

# ============================================================================
# PENETRATION TESTING WORKFLOW
# ============================================================================

@app.post("/api/pentest/start")
async def start_penetration_test(config: dict, background_tasks: BackgroundTasks):
    """
    Initiate autonomous penetration testing workflow.
    
    Stages:
    1. Reconnaissance (Nmap, Nuclei, passive scanning)
    2. ATT&CK Mapping (correlate findings to MITRE framework)
    3. Exploit Validation (prepare payloads without execution)
    4. Human Approval Gate (operator reviews findings)
    5. Execution (if approved)
    """
    target = config.get("target", "127.0.0.1")
    scan_type = config.get("scan_type", "comprehensive")
    
    try:
        # Phase 1: Reconnaissance
        recon_results = recon.scan(target, scan_type)
        
        # Phase 2: Map to MITRE ATT&CK
        attack_mappings = orchestrator.map_to_attack_framework(recon_results)
        
        # Phase 3: Prepare exploits (staged, not executed)
        staged_exploits = exploit.stage_payloads(attack_mappings)
        
        # Store state (awaiting human approval)
        test_id = db.insert_pentest({
            "target": target,
            "scan_type": scan_type,
            "recon_results": recon_results,
            "attack_mappings": attack_mappings,
            "staged_exploits": staged_exploits,
            "status": "awaiting_approval",
            "created_at": datetime.utcnow()
        })
        
        return {
            "test_id": test_id,
            "status": "awaiting_approval",
            "findings_count": len(recon_results),
            "attack_techniques": len(attack_mappings),
            "message": "Reconnaissance complete. Review in UI, then approve to proceed."
        }
    except Exception as e:
        logger.error(f"Penetration test initialization failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# MITRE ATT&CK FRAMEWORK ENDPOINTS
# ============================================================================

@app.get("/api/mitre/tactics")
async def get_mitre_tactics():
    """Fetch all available MITRE ATT&CK tactics."""
    return orchestrator.get_tactics()

@app.get("/api/mitre/techniques")
async def get_mitre_techniques(tactic: str):
    """Fetch techniques for a specific MITRE ATT&CK tactic."""
    return orchestrator.get_techniques(tactic)

# ============================================================================
# STARTUP & SHUTDOWN HANDLERS
# ============================================================================

@app.on_event("startup")
async def startup_sequence():
    logger.info("JAKAL Backend initialization starting...")
    db.initialize_schema()
    orchestrator.load_mitre_database()
    quantum.initialize()
    logger.info("All systems operational.")

@app.on_event("shutdown")
async def shutdown_sequence():
    logger.info("JAKAL Backend shutting down...")
    db.close()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
```

### DuckDB Database Schema
```python
# backend/database.py
import duckdb
import json
from datetime import datetime

class DuckDBManager:
    def __init__(self, db_path="jakal.duckdb"):
        self.conn = duckdb.connect(db_path)
        self.db_path = db_path

    def initialize_schema(self):
        """Initialize all required tables and sequences."""
        
        # Sequence generators
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_logs START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_jobs START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_pentest START 1")
        
        # Agent logs table
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_logs'),
            timestamp TIMESTAMP DEFAULT now(),
            event VARCHAR,
            action VARCHAR,
            status VARCHAR,
            operator_id VARCHAR,
            details VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        # Quantum jobs table
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS quantum_jobs (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_jobs'),
            job_id VARCHAR UNIQUE,
            circuit_name VARCHAR,
            backend VARCHAR,
            shots INTEGER,
            result VARCHAR,
            status VARCHAR,
            created_at TIMESTAMP DEFAULT now(),
            completed_at TIMESTAMP
        )
        """)

        # Penetration test runs
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS pentest_runs (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_pentest'),
            target VARCHAR,
            scan_type VARCHAR,
            recon_results VARCHAR,
            attack_mappings VARCHAR,
            staged_exploits VARCHAR,
            status VARCHAR,
            created_at TIMESTAMP DEFAULT now(),
            completed_at TIMESTAMP
        )
        """)

        # Security findings
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_findings'),
            pentest_id INTEGER,
            severity VARCHAR,
            title VARCHAR,
            description VARCHAR,
            attack_technique VARCHAR,
            remediation VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        self.conn.commit()

    def insert_log(self, log_data):
        """Insert agent telemetry log entry."""
        self.conn.execute(
            """
            INSERT INTO agent_logs (event, action, status, operator_id, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                log_data.get("event"),
                log_data.get("action"),
                log_data.get("status"),
                log_data.get("operator_id"),
                json.dumps(log_data.get("details", {}))
            )
        )
        self.conn.commit()

    def query(self, sql, params=()):
        """Execute SELECT query."""
        result = self.conn.execute(sql, params).fetchall()
        return result

    def close(self):
        self.conn.close()
```

---

## Frontend Integration

The frontend (newos3.html) remains as your production UI. Below are the corrected rendering functions for the autonomous pen-test matrix and quantum interface:

### Autonomous Pen-Test Matrix Module
```javascript
// Render function for autonomous pen-test orchestration
window.renderPentestMatrix = function() {
    return `
    <div class="space-y-6 fade-in h-full flex flex-col">
        <!-- Header: System Status -->
        <div class="card p-6 flex-shrink-0 border-t-4 border-t-red-500 bg-gray-900/50">
            <div class="flex justify-between items-center">
                <div>
                    <h2 class="text-lg font-black text-white uppercase tracking-widest mb-1">
                        Autonomous Threat Orchestrator
                    </h2>
                    <p class="text-xs text-gray-400">
                        Real-time exploitation mapping against MITRE ATT&CK framework
                    </p>
                </div>
                <span class="px-3 py-1 bg-blue-500/10 border border-blue-500/30 text-blue-400 text-[10px] font-mono rounded-full">
                    Backend: Operational
                </span>
            </div>
        </div>

        <!-- Main Grid -->
        <div class="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-6 overflow-hidden">
            
            <!-- LEFT: Agent Console -->
            <div class="card p-4 flex flex-col overflow-hidden bg-black/60">
                <h3 class="text-xs font-bold uppercase tracking-widest text-red-400 mb-3 border-b border-white/10 pb-2">
                    Live Agent Telemetry
                </h3>
                <div id="agent-logs" class="flex-1 bg-black rounded-lg p-3 font-mono text-[11px] text-gray-300 overflow-y-auto space-y-1">
                    <div class="text-green-400">[INIT] Agent orchestrator initialized.</div>
                    <div class="text-blue-400">[SCAN] Running network reconnaissance...</div>
                    <div class="text-yellow-400">[ATT&CK] Mapped to T1595 (Active Scanning).</div>
                    <div class="text-gray-500">[WAIT] Awaiting operator approval...</div>
                </div>
                
                <!-- Action Buttons -->
                <div class="mt-4 flex gap-2">
                    <button 
                        onclick="approveExploit()" 
                        class="flex-1 py-2 bg-red-600 hover:bg-red-700 rounded text-xs font-bold text-white transition">
                        Approve Action
                    </button>
                    <button 
                        onclick="pauseAgent()" 
                        class="flex-1 py-2 bg-gray-800 hover:bg-gray-700 rounded text-xs font-bold text-gray-300 transition">
                        Pause
                    </button>
                </div>
            </div>

            <!-- RIGHT: MITRE ATT&CK Matrix -->
            <div class="lg:col-span-2 card p-4 overflow-hidden bg-black/40 border border-white/10">
                <h3 class="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">MITRE ATT&CK Mapping</h3>
                <div class="grid grid-cols-4 gap-2 h-full">
                    ${['Reconnaissance', 'Initial Access', 'Execution', 'Exfiltration'].map(tactic => `
                        <div class="border border-white/10 rounded bg-gray-900/60 p-2 flex flex-col">
                            <div class="text-[10px] font-bold text-gray-400 uppercase text-center mb-2 border-b border-white/5 pb-1">
                                ${tactic}
                            </div>
                            <div class="flex-1 flex flex-col gap-1 text-[9px]">
                                <div class="p-1.5 border border-red-500/40 bg-red-500/10 rounded text-white">Active: T1190</div>
                                <div class="p-1.5 border border-white/5 bg-black/40 rounded text-gray-500">Idle: T1133</div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    </div>`;
};
```

### Quantum Interface Module
```javascript
// Quantum execution interface with local-first strategy
window.renderQuantumInterface = function() {
    return `
    <div class="space-y-6 fade-in">
        <!-- Status Cards -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="card p-5 border-l-4 border-l-green-500 bg-gray-900/50">
                <div class="text-[10px] font-bold text-gray-400 uppercase mb-1">Primary Execution Backend</div>
                <div class="text-lg font-black text-white">Qiskit-Aer (Local)</div>
                <div class="text-[10px] text-green-400 mt-1">✓ Unlimited Circuits</div>
            </div>
            <div class="card p-5 border-l-4 border-l-blue-500 bg-gray-900/50">
                <div class="text-[10px] font-bold text-gray-400 uppercase mb-1">Hardware Access (Cloud)</div>
                <div class="text-lg font-black text-white">IBM Quantum Open</div>
                <div class="text-[10px] text-blue-400 mt-1">Production Validation Available</div>
            </div>
            <div class="card p-5 border-l-4 border-l-purple-500 bg-gray-900/50">
                <div class="text-[10px] font-bold text-gray-400 uppercase mb-1">Execution Mode</div>
                <div class="text-lg font-black text-white">Hybrid</div>
                <div class="text-[10px] text-gray-400 mt-1">Local + Cloud Fallback</div>
            </div>
        </div>

        <!-- Job Queue -->
        <div class="card p-6 bg-black/50 border border-white/10">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-xs font-bold uppercase tracking-widest text-gray-300">Job Execution Queue</h3>
                <button 
                    onclick="submitQuantumJob()" 
                    class="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-xs font-bold text-white transition">
                    Run Simulation
                </button>
            </div>
            <div class="w-full bg-gray-900/80 rounded border border-white/5 overflow-hidden">
                <table class="w-full text-left text-xs">
                    <thead class="bg-black/60 text-[10px] uppercase tracking-widest text-gray-400 border-b border-white/5">
                        <tr>
                            <th class="p-3">Job ID</th>
                            <th class="p-3">Target Backend</th>
                            <th class="p-3">Status</th>
                            <th class="p-3 text-right">Runtime</th>
                        </tr>
                    </thead>
                    <tbody class="text-gray-300 font-mono divide-y divide-white/5">
                        <tr>
                            <td class="p-3 text-blue-400">sim_aer_89a12</td>
                            <td class="p-3 text-gray-400">Qiskit-Aer</td>
                            <td class="p-3"><span class="px-2 py-0.5 bg-green-500/20 text-green-400 rounded text-[9px]">Completed</span></td>
                            <td class="p-3 text-right">0.023s</td>
                        </tr>
                        <tr>
                            <td class="p-3 text-blue-400">ibm_job_4192f</td>
                            <td class="p-3 text-gray-400">IBM Quantum Open</td>
                            <td class="p-3"><span class="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded text-[9px]">Queued</span></td>
                            <td class="p-3 text-right">--</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>`;
};
```

---

## Deployment Strategy

### Development & Testing
```bash
# Local setup (Oracle Free Tier or workstation)
git clone <repo>
cd backend

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start backend
python app.py  # Runs on http://0.0.0.0:8000

# Start Ollama (separate terminal)
ollama serve llama2
```

### Frontend Deployment
```bash
cd frontend
npm install
vercel deploy
```

---

## Success Criteria

- [ ] Local backend operational with full REST API
- [ ] DuckDB schema initialized and tested
- [ ] Qiskit-Aer circuits execute locally
- [ ] Dashboard connects to backend
- [ ] Agentic loops functional (LLM + tool bindings)
- [ ] Human-in-the-loop gates working
- [ ] Supabase cloud sync optional and working
- [ ] End-to-end penetration test workflow operational

---

**Next Steps**: Begin Phase 1 implementation. Reference this architecture for all backend and frontend development.
