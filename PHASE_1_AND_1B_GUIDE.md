# JAKAL Implementation Guide - Phases 1 & 1B
## Complete Setup & Deployment Instructions

---

## Pre-Implementation Checklist

Before starting, ensure you have:

- ✅ Completed Phase 0 (all accounts created)
- ✅ `.env` file created with all credentials
- ✅ `oracle_key.pem` saved securely
- ✅ SSH access to Oracle instance verified
- ✅ Python 3.11+ installed locally
- ✅ Git installed and configured
- ✅ Docker installed (for later phases)

---

## Step 1: Initialize Local Development Environment

### 1.1 Create Project Directory

```bash
# Create project root
mkdir ~/projects/JAKAL
cd ~/projects/JAKAL

# Initialize git
git init
git remote add origin https://github.com/YOUR_USERNAME/JAKAL.git

# Create directory structure
mkdir -p backend/{security_agents,tools,integrations,schemas,tests}
mkdir -p frontend/{components,styles,pages,public}
mkdir -p "GACyber Tool Kit"/{01-Reconnaissance,02-Scanning,03-Enumeration,04-Web-Application,05-Wireless,06-Exploitation,07-Post-Exploitation,Resources,CheatSheets}
mkdir -p configs
mkdir -p docs
mkdir -p logs
mkdir -p data
mkdir -p backups
mkdir -p tests
```

### 1.2 Create Virtual Environment

```bash
# Create Python virtual environment
python3 -m venv venv

# Activate it (Linux/Mac)
source venv/bin/activate

# Activate it (Windows)
venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip setuptools wheel
```

### 1.3 Install Dependencies

```bash
# Copy provided requirements.txt to backend/
cp requirements.txt backend/

# Install all Python dependencies
pip install -r backend/requirements.txt

# Verify installation
python -c "import fastapi; import duckdb; print('✅ Dependencies installed')"
```

---

## Step 2: Create Backend Structure

### 2.1 Copy Phase 1 Files

Copy the following files into your project:

```
backend/
├── app.py              ← Copy from phase1_app.py
├── database.py         ← Copy from phase1_database.py
├── config.py           ← Copy from phase1_config.py
└── requirements.txt    ← Already copied above

tools/
└── authorization.py    ← Copy from phase1b_authorization.py

.env                    ← Create from .env.example
.env.example            ← Provided template
.gitignore             ← Create with sensitive files
```

### 2.2 Create .gitignore

```bash
cat > .gitignore << 'EOF'
# Credentials (NEVER commit)
.env
.env.local
.env.*.local
*.pem
*-service-account.json
*-credentials.json

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Database
*.duckdb
*.duckdb-shm
*.duckdb-wal
*.db
*.sqlite

# Logs
logs/
*.log

# Backups
backups/
*.bak
*.backup

# Temporary
temp/
tmp/
*.tmp

# OS
.DS_Store
Thumbs.db
.env.*.swp
EOF
```

### 2.3 Populate .env

```bash
# Copy template
cp .env.example .env

# Edit .env with your actual credentials
nano .env  # or use your editor

# Verify it's in .gitignore
grep "^.env" .gitignore
```

---

## Step 3: Initialize Database

### 3.1 Test Database Connection

```bash
# Create a simple test script
cat > test_db.py << 'EOF'
#!/usr/bin/env python3
import os
from backend.database import DuckDBManager
from backend.config import get_config

# Load config
config = get_config()

# Initialize database manager
db = DuckDBManager(config.database_url)

# Initialize schema
db.initialize_schema()

# Verify tables created
tables = db.query("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'main'
""")

print("✅ Database initialized successfully!")
print(f"📊 Created {len(tables)} tables:")
for table in tables:
    print(f"   - {table[0]}")

db.close()
EOF

# Run test
python test_db.py
```

### 3.2 Expected Output

```
✅ Database initialized successfully!
📊 Created 12 tables:
   - agent_logs
   - quantum_jobs
   - pentest_runs
   - findings
   - attack_mappings
   - scopes
   - insurance_policies
   - compliance_checkpoints
   - operators
   - assessment_reports
   - rfp_responses
   - (indexes)
```

---

## Step 4: Set Up Authorization & Compliance

### 4.1 Add Test Data

```bash
# Create initialization script
cat > init_auth.py << 'EOF'
#!/usr/bin/env python3
import os
from datetime import datetime, timedelta
from backend.database import DuckDBManager
from backend.config import get_config
from backend.tools.authorization import AuthorizationGate

# Load config
config = get_config()

# Initialize database
db = DuckDBManager(config.database_url)

# Create authorization gate
auth_gate = AuthorizationGate(db, config)

# 1. Add test operator
db.execute("""
    INSERT OR IGNORE INTO operators (operator_id, email, role, active)
    VALUES ('test_operator', 'test@example.com', 'operator', true)
""")

# 2. Add test scope
auth_gate.add_scope(
    scope_id="test_scope",
    client_name="Test Client",
    target_ips="192.168.1.0/24,10.0.0.0/8",
    target_domains="example.com,test.example.com",
    roe_path="/path/to/roe.pdf"
)

# 3. Add test insurance policy (1 year from now)
expiry_date = (datetime.utcnow() + timedelta(days=365)).isoformat()
auth_gate.add_insurance_policy(
    policy_number="TEST-POL-001",
    provider="Cyber Insurance Co",
    coverage_amount=1000000,
    expiry_date=expiry_date
)

print("✅ Authorization data initialized!")
print("\n📋 Active Scopes:")
for scope in auth_gate.list_active_scopes():
    print(f"   - {scope['scope_id']}: {scope['target_ips']}")

print("\n🛡️ Active Insurance:")
for policy in auth_gate.list_active_insurance():
    print(f"   - {policy['policy_number']}: ${policy['coverage_amount']}")

db.close()
EOF

# Run initialization
python init_auth.py
```

### 4.2 Test Authorization Gate

```bash
# Create test script
cat > test_auth.py << 'EOF'
#!/usr/bin/env python3
from backend.database import DuckDBManager
from backend.config import get_config
from backend.tools.authorization import AuthorizationGate

config = get_config()
db = DuckDBManager(config.database_url)
auth = AuthorizationGate(db, config)

# Test 1: Authorized target
try:
    result = auth.check_authorization_and_scope(
        target="192.168.1.100",
        action="scan",
        operator_id="test_operator"
    )
    print(f"✅ Test 1 PASSED: {result.reason}")
except PermissionError as e:
    print(f"❌ Test 1 FAILED: {str(e)}")

# Test 2: Unauthorized target
try:
    result = auth.check_authorization_and_scope(
        target="8.8.8.8",  # Google DNS (not in scope)
        action="scan",
        operator_id="test_operator"
    )
    print(f"❌ Test 2 FAILED: Should have been blocked")
except PermissionError as e:
    print(f"✅ Test 2 PASSED: Correctly blocked - {str(e)}")

# Test 3: Invalid operator
try:
    result = auth.check_authorization_and_scope(
        target="192.168.1.100",
        action="scan",
        operator_id="nonexistent_operator"
    )
    print(f"❌ Test 3 FAILED: Should have been blocked")
except PermissionError as e:
    print(f"✅ Test 3 PASSED: Correctly blocked - {str(e)}")

db.close()
EOF

# Run tests
python test_auth.py
```

---

## Step 5: Start FastAPI Backend

### 5.1 Development Mode

```bash
# Run backend locally
cd backend
python app.py

# Or with uvicorn directly
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Expected output:
# INFO:     Uvicorn running on http://0.0.0.0:8000
# INFO:     Application startup complete
```

### 5.2 Test API Endpoints

**In another terminal:**

```bash
# Test health endpoint
curl http://localhost:8000/health

# Expected response:
# {
#   "status": "operational",
#   "timestamp": "2024-01-15T10:30:45.123456",
#   "backend": "fastapi",
#   "database": "healthy",
#   "environment": "development",
#   "version": "1.0.0"
# }

# Test system status
curl http://localhost:8000/api/system/status

# Test agent logs (empty at first)
curl http://localhost:8000/api/agent/logs

# List database tables
curl http://localhost:8000/api/database/tables
```

### 5.3 Access API Documentation

Open browser: `http://localhost:8000/docs`

You should see Swagger UI with all endpoints documented.

---

## Step 6: Deploy to Oracle Cloud

### 6.1 SSH into Oracle Instance

```bash
# Set key permissions
chmod 600 oracle_key.pem

# SSH into instance
ssh -i oracle_key.pem ubuntu@YOUR_ORACLE_IP

# On Oracle instance, verify system
uname -a
df -h
free -h
```

### 6.2 Install Dependencies on Oracle

```bash
# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install Python & tools
sudo apt-get install -y python3.11 python3-pip python3-venv git curl wget

# Install security tools (for later phases)
sudo apt-get install -y nmap nikto dnsmasq

# Verify installations
python3 --version
pip3 --version
nmap --version
```

### 6.3 Clone & Setup Project on Oracle

```bash
# Clone repository
git clone https://github.com/YOUR_USERNAME/JAKAL.git
cd JAKAL

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Setup environment
cp .env.example .env
nano .env  # Fill in Oracle-specific values

# Test local startup
python backend/app.py

# Ctrl+C to stop
```

### 6.4 Run Backend as Service (Production)

```bash
# Create systemd service file
sudo nano /etc/systemd/system/jakal-backend.service
```

Paste:

```ini
[Unit]
Description=JAKAL Enterprise Backend
After=network.target

[Service]
Type=notify
User=ubuntu
WorkingDirectory=/home/ubuntu/JAKAL
Environment="PATH=/home/ubuntu/JAKAL/venv/bin"
ExecStart=/home/ubuntu/JAKAL/venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable jakal-backend
sudo systemctl start jakal-backend

# Check status
sudo systemctl status jakal-backend

# View logs
sudo journalctl -u jakal-backend -f

# Test from your local machine
curl http://YOUR_ORACLE_IP:8000/health
```

---

## Step 7: Testing Checklist

```
✅ Database initialized with all 12 tables
✅ Authorization gate working (approves authorized, blocks unauthorized)
✅ Operators table populated with test user
✅ Scopes table has test RoE entries
✅ Insurance policies table has active policy
✅ /health endpoint returns 200
✅ /api/system/status provides detailed status
✅ /api/agent/logs endpoint functional
✅ /api/database/tables lists all tables
✅ Backend runs locally on port 8000
✅ Backend runs on Oracle Cloud instance
✅ Systemd service auto-restarts on failure
✅ API docs accessible at /docs
```

---

## Phase 1 & 1B Completion Summary

**Deliverables:**
- ✅ FastAPI backend structure
- ✅ DuckDB schema with 12 tables
- ✅ Configuration management system
- ✅ Authorization & compliance framework
- ✅ Running on local machine
- ✅ Deployed to Oracle Cloud instance
- ✅ Systemd service for production uptime

**Next: Phase 2 - LLM & Quantum Integration**

