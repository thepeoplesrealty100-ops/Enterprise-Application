# JAKAL FULL BUILD & DEPLOYMENT - PHASES 2-5 EXECUTION GUIDE

**Current Status:** Phase 1 ✅ Complete - Local environment ready  
**Next:** Phase 2-5 (Dependencies, Docker, Oracle Deployment)

---

## 🚀 PHASE 2: DEPENDENCIES & LOCAL INTEGRATION (2-3 hours)

### Step 1: Copy Phase 1 Foundation Files

From `C:\Users\Freddy\AppData\Roaming\Docker\cagent\` copy to `C:\Users\Freddy\projects\JAKAL\`:

```powershell
# Copy these files
Copy-Item "C:\Users\Freddy\AppData\Roaming\Docker\cagent\phase1_app.py" -Destination "C:\Users\Freddy\projects\JAKAL\backend\app.py"
Copy-Item "C:\Users\Freddy\AppData\Roaming\Docker\cagent\phase1_database.py" -Destination "C:\Users\Freddy\projects\JAKAL\backend\database.py"
Copy-Item "C:\Users\Freddy\AppData\Roaming\Docker\cagent\phase1_config.py" -Destination "C:\Users\Freddy\projects\JAKAL\backend\config.py"
Copy-Item "C:\Users\Freddy\AppData\Roaming\Docker\cagent\phase1b_authorization.py" -Destination "C:\Users\Freddy\projects\JAKAL\backend\tools\authorization.py"
Copy-Item "C:\Users\Freddy\AppData\Roaming\Docker\cagent\requirements.txt" -Destination "C:\Users\Freddy\projects\JAKAL\requirements.txt"
Copy-Item "C:\Users\Freddy\AppData\Roaming\Docker\cagent\.env.example" -Destination "C:\Users\Freddy\projects\JAKAL\.env.example"
```

### Step 2: Create missing __init__.py

```powershell
mkdir "C:\Users\Freddy\projects\JAKAL\backend\tools" -ErrorAction SilentlyContinue
"# Tools package" | Out-File "C:\Users\Freddy\projects\JAKAL\backend\tools\__init__.py"
```

### Step 3: Update app.py with Phase 2 Integration

Add to `backend/app.py` imports:
```python
from backend.llm_orchestrator import LLMOrchestrator
from backend.quantum_engine import QuantumEngine
from backend.routers.phase2_api import create_phase2_router
```

Add to lifespan startup:
```python
llm_orchestrator = LLMOrchestrator(config)
quantum_engine = QuantumEngine(config)
```

Add before main block:
```python
phase2_router = create_phase2_router(llm_orchestrator, quantum_engine, db_manager)
app.include_router(phase2_router)
```

### Step 4: Update requirements.txt

Append these to requirements.txt:
```
google-generativeai==0.3.0
qiskit==0.43.3
qiskit-aer==0.13.1
qiskit-ibm-runtime==0.20.0
aiohttp==3.9.1
whois==0.9
python-whois==0.7.3
```

### Step 5: Test Phase 2 Locally

```powershell
# Navigate to project
cd "C:\Users\Freddy\projects\JAKAL"

# Create & activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Start backend
cd backend
python app.py

# In another PowerShell, test endpoints:
curl http://localhost:8000/health
curl http://localhost:8000/api/llm/health
curl http://localhost:8000/api/quantum/health
```

---

## 🐳 PHASE 3: DOCKER CONTAINERIZATION (1-2 hours)

### Step 1: Copy Docker Files

```powershell
Copy-Item "C:\Users\Freddy\AppData\Roaming\Docker\cagent\Dockerfile" -Destination "C:\Users\Freddy\projects\JAKAL\Dockerfile"
Copy-Item "C:\Users\Freddy\AppData\Roaming\Docker\cagent\docker-compose.yml" -Destination "C:\Users\Freddy\projects\JAKAL\docker-compose.yml"
```

### Step 2: Create .dockerignore

Create `C:\Users\Freddy\projects\JAKAL\.dockerignore`:
```
__pycache__
*.pyc
.env
.env.local
*.pem
*-service-account.json
.git
.gitignore
.vscode
.idea
node_modules
dist
build
*.egg-info
.pytest_cache
*.log
.venv
venv
```

### Step 3: Build Docker Image

```powershell
cd "C:\Users\Freddy\projects\JAKAL"

# Build image
docker build -t jakal-backend:latest -f Dockerfile .

# Verify
docker images | Select-String jakal
```

### Step 4: Test Docker Locally

```powershell
# Start containers
docker-compose up -d

# Wait 10 seconds
Start-Sleep -Seconds 10

# Check status
docker ps
docker logs jakal-backend

# Test
curl http://localhost:8000/health

# Shutdown
docker-compose down
```

---

## ☁️ PHASE 4: ORACLE CLOUD DEPLOYMENT (1-2 hours)

### Step 1: SSH to Oracle Instance

```powershell
# SSH to Oracle
ssh -i "C:\Users\Freddy\projects\JAKAL\oracle_key.pem" ubuntu@YOUR_ORACLE_IP

# On Oracle instance:
cd ~
git clone https://github.com/YOUR_USERNAME/JAKAL.git
cd JAKAL
```

### Step 2: Install Docker on Oracle

```bash
# On Oracle instance
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker
```

### Step 3: Setup Environment

```bash
# On Oracle
cp .env.example .env
# Edit .env with your credentials
nano .env

# Add credentials:
# GEMINI_API_KEY=your_key_here
# IBM_QUANTUM_TOKEN=your_token_here
# etc.

# Create directories
mkdir -p data logs backups
```

### Step 4: Build & Deploy

```bash
# On Oracle
docker build -t jakal-backend:latest .
docker-compose up -d

# Wait 15 seconds
sleep 15

# Check logs
docker logs jakal-backend

# Test
curl http://localhost:8000/health
```

---

## 🔒 PHASE 5: FIREWALL & PRODUCTION VERIFICATION (30 minutes)

### Step 1: Configure Firewall

```bash
# On Oracle instance
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8000/tcp
sudo ufw enable
sudo ufw status
```

### Step 2: Verify Endpoints

From your local machine:

```powershell
# Replace YOUR_ORACLE_IP with actual IP
$ORACLE_IP = "YOUR_ORACLE_IP"

# Health check
curl http://$ORACLE_IP:8000/health

# System status
curl http://$ORACLE_IP:8000/api/system/status

# LLM health
curl http://$ORACLE_IP:8000/api/llm/health

# Quantum health
curl http://$ORACLE_IP:8000/api/quantum/health

# View API docs
# Open browser: http://$ORACLE_IP:8000/docs
```

### Step 3: Setup Automated Backups

```bash
# On Oracle
cat > backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/home/ubuntu/JAKAL/backups"
DATE=$(date +%Y%m%d_%H%M%S)
cp /home/ubuntu/JAKAL/data/jakal.duckdb $BACKUP_DIR/jakal_$DATE.duckdb
find $BACKUP_DIR -type f -mtime +7 -delete
echo "Backup complete: $DATE"
EOF

chmod +x backup.sh

# Add to crontab
crontab -e
# Add line: 0 2 * * * /home/ubuntu/JAKAL/backup.sh
```

---

## ✅ FINAL VERIFICATION CHECKLIST

```
✅ Phase 2: Local Backend
  - [ ] Backend starts without errors
  - [ ] /health endpoint returns 200
  - [ ] /api/llm/health responds
  - [ ] /api/quantum/health responds
  - [ ] All 55+ endpoints visible at /docs

✅ Phase 3: Docker
  - [ ] Image builds successfully
  - [ ] docker-compose up -d starts without errors
  - [ ] Container health checks pass
  - [ ] Endpoints accessible on localhost:8000
  - [ ] docker-compose down removes cleanly

✅ Phase 4: Oracle Deployment
  - [ ] SSH connection successful
  - [ ] Docker installed on Oracle
  - [ ] Image builds on Oracle
  - [ ] Containers start and persist
  - [ ] All endpoints accessible on Oracle IP:8000

✅ Phase 5: Production Ready
  - [ ] Firewall rules configured (22, 80, 443, 8000)
  - [ ] External endpoints respond
  - [ ] Backup script scheduled
  - [ ] Monitoring logs visible
  - [ ] System stable for 24+ hours
```

---

## 🎯 SYSTEM CAPACITY AFTER DEPLOYMENT

- ✅ 55+ REST API endpoints
- ✅ 7 CPENT phase agents (automated)
- ✅ LLM reasoning (Gemini + Ollama)
- ✅ Quantum simulation (Qiskit)
- ✅ MITRE ATT&CK mapping
- ✅ Immutable audit logging
- ✅ Multi-user authentication
- ✅ $0/month baseline cost

---

## 📞 TROUBLESHOOTING

### Backend won't start
```powershell
# Check Python version
python --version  # Should be 3.11+

# Check dependencies
pip list | Select-String fastapi

# Reinstall requirements
pip install --force-reinstall -r requirements.txt
```

### Docker image won't build
```bash
# Check Dockerfile syntax
docker build --no-cache -t jakal:latest .

# View detailed build logs
docker build --progress=plain -t jakal:latest .
```

### Oracle endpoint not responding
```bash
# SSH to Oracle and check:
docker ps  # Is container running?
docker logs jakal-backend  # Any errors?
curl localhost:8000/health  # Local test
sudo ufw status  # Firewall rules?
```

---

## 🚀 YOU ARE READY

All phases are executable. Follow sequentially:
1. Phase 2: Local testing (2-3 hours)
2. Phase 3: Docker verification (1-2 hours)
3. Phase 4: Oracle deployment (1-2 hours)
4. Phase 5: Production verification (30 min)

**Total: 5-7 hours to production-ready system**

Begin Phase 2 now!
