# JAKAL Phase 0: Account Setup & Infrastructure Provisioning
## Step-by-Step Account Creation Guide

**Timeline:** 2-4 hours to complete all account setup  
**Cost:** $0 (all free/open-source tiers used)

---

## Account 1: Oracle Cloud Always-Free Tier (Backend Compute)

### Why Oracle?
- 4 ARM cores (always-free)
- 24GB RAM (always-free)
- 200GB storage (always-free)
- **Unlimited always-on uptime** (no auto-suspend like AWS)
- $0/month cost

### Setup Steps

1. **Visit:** https://www.oracle.com/cloud/free/
2. **Click:** "Start for free" button
3. **Create Oracle Account:**
   - Email address
   - Password (strong: 12+ chars, uppercase, numbers, symbols)
   - First & Last name
   - Company name (can be fictional)
   - Country

4. **Verify Email** (check inbox for Oracle verification link)

5. **Add Payment Method:**
   - Credit/debit card (required for verification, will NOT be charged)
   - Billing address

6. **Accept Terms & Conditions**

7. **Cloud Account Created** - Login to https://cloud.oracle.com/

### Provision Compute Instance

8. **Navigate:** Dashboard → Compute → Instances
9. **Click:** "Create Instance"
10. **Configure:**
    - **Name:** `jakal-backend-prod`
    - **Image:** Ubuntu 22.04 LTS (free tier eligible)
    - **Instance Shape:** Ampere (ARM) - VM.Standard.A1.Compute (4 OCPUs, 24GB RAM)
    - **VCN:** Create new or use default
    - **Public IP:** Assign (important for remote access)
    - **SSH Key:** Generate new keypair
      - Download `.key` file → save as `oracle_key.pem`
      - **CRITICAL:** Keep this file safe (do NOT commit to git)

11. **Create Instance** (2-3 minutes)

12. **Once Running, Note:**
    - Public IP address (e.g., `1.2.3.4`)
    - Username: `ubuntu`
    - SSH command: `ssh -i oracle_key.pem ubuntu@1.2.3.4`

### Test SSH Connection

```bash
# Set proper permissions
chmod 600 oracle_key.pem

# Test connection
ssh -i oracle_key.pem ubuntu@YOUR_ORACLE_IP

# Should see: ubuntu@jakal-backend-prod:~$
# If yes: ✅ Oracle instance ready

# Exit
exit
```

### Save to Credentials Vault
```
ORACLE_INSTANCE_IP=YOUR_IP_HERE
ORACLE_SSH_KEY_PATH=./oracle_key.pem
ORACLE_USERNAME=ubuntu
```

---

## Account 2: Supabase (Cloud Database)

### Why Supabase?
- PostgreSQL 15 (managed)
- 500MB storage (free tier)
- Unlimited REST API calls
- Real-time WebSocket subscriptions
- Row-level security (RLS)
- $0/month for free tier

### Setup Steps

1. **Visit:** https://supabase.com/
2. **Click:** "Sign up" (use GitHub for faster signup)
3. **Authorize:** Connect GitHub account (optional, can use email)
4. **Create Workspace:**
   - Workspace name: `jakal-enterprise`
   - Accept terms

5. **Create Project:**
   - Project name: `jakal-production`
   - Database password: Generate strong one (save it!)
   - Region: Choose closest to your location
   - Plan: Free

6. **Wait:** Database provisioning (1-2 minutes)

### Save Connection Details

7. **Project Settings → Database:**
   - **URI:** https://xxxxx.supabase.co
   - **Public API Key:** (anon key) - start with `eyJ...`
   - **Service Role Key:** (secret) - copy & save securely
   - **Database Password:** (save separately)

8. **Connection String:**
   ```
   postgresql://postgres:PASSWORD@db.xxxxx.supabase.co:5432/postgres
   ```

### Save to Credentials Vault
```
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...
SUPABASE_DB_PASSWORD=...
DATABASE_URL=postgresql://...
```

---

## Account 3: Firebase Authentication

### Why Firebase?
- Google Sign-in integration
- Unlimited free users
- JWT token-based auth
- Admin SDK for backend
- $0/month for free tier

### Setup Steps

1. **Visit:** https://console.firebase.google.com/
2. **Create New Project:**
   - Project name: `jakal-auth`
   - Accept data processing terms
   - Disable Analytics (optional)

3. **Wait:** Project creation (30-60 seconds)

4. **Setup Authentication:**
   - Left sidebar → Authentication
   - Click: "Get Started"
   - Enable providers:
     - ✅ Google
     - ✅ Email/Password
     - ✅ GitHub (optional)

5. **Project Settings (gear icon):**
   - **Project ID:** Copy (e.g., `jakal-auth-abc123`)
   - **Web API Key:** Copy (starts with `AIza...`)

6. **Generate Service Account Key:**
   - Settings → Service Accounts
   - Click: "Generate New Private Key"
   - Save JSON file as `firebase-service-account.json`
   - **CRITICAL:** Do NOT commit this to git

### Save to Credentials Vault
```
FIREBASE_PROJECT_ID=jakal-auth-abc123
FIREBASE_WEB_API_KEY=AIza...
FIREBASE_SERVICE_ACCOUNT_KEY=./firebase-service-account.json
```

---

## Account 4: Google Cloud Gemini API

### Why Gemini?
- State-of-the-art LLM (1.5 Flash model)
- Free tier: 60 requests/minute
- Fast inference (< 1 sec per request)
- $0/month for free tier (100K free tokens/month)

### Setup Steps

1. **Visit:** https://console.cloud.google.com/
2. **Create New Project:**
   - Project name: `jakal-gemini`
   - Organization: (leave default)
   - Create

3. **Wait:** Project creation

4. **Enable Generative AI API:**
   - Search bar: "Generative AI API"
   - Click: "Enable"
   - Wait for enablement

5. **Create API Key:**
   - Left sidebar → APIs & Services → Credentials
   - Click: "Create Credentials" → "API Key"
   - Copy the API key (starts with `AI...`)
   - **CRITICAL:** Restrict this key to Google AI Generative API only:
     - Click pencil icon → Edit
     - API restrictions → Restrict key
     - Select: "Generative Language API"
     - Save

### Test Gemini Connection
```bash
curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Hello, Gemini!"}]}]}'

# Should return: { "candidates": [...] }
# If yes: ✅ Gemini API working
```

### Save to Credentials Vault
```
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-1.5-flash
```

---

## Account 5: IBM Quantum Open Plan

### Why IBM Quantum?
- Real quantum hardware access (10 free minutes/month)
- Local Qiskit-Aer simulator (unlimited)
- Great for quantum circuit development
- Educational/research: free

### Setup Steps

1. **Visit:** https://quantum.ibm.com/
2. **Sign Up / Login:**
   - Create IBM account (or use existing)
   - Verify email

3. **Create API Token:**
   - Account settings (top-right)
   - Manage your API tokens
   - Create new token
   - Copy token (save securely)

4. **Join Open Plan:**
   - Dashboard → Plans & pricing
   - Enroll in "Open Plan" (free)
   - Confirm

5. **Test Connection:**
```python
from qiskit_ibm_runtime import QiskitRuntimeService

QiskitRuntimeService.save_account(
    channel="ibm_quantum",
    instance="ibm-q/open/main",
    token="YOUR_IBM_TOKEN"
)

# Should display: Account saved successfully
# If yes: ✅ IBM Quantum ready
```

### Save to Credentials Vault
```
IBM_QUANTUM_TOKEN=...
IBM_QUANTUM_INSTANCE=ibm-q/open/main
```

---

## Account 6: GitHub Repository

### Why GitHub?
- Version control
- CI/CD integration (GitHub Actions)
- Community hosting
- Free private repos

### Setup Steps

1. **Visit:** https://github.com/ (if not already account)
2. **Create New Repository:**
   - Name: `JAKAL`
   - Description: `Enterprise Autonomous Penetration Testing Platform`
   - Visibility: Public (for portfolio) or Private (for commercial)
   - Add README: Yes
   - Add .gitignore: Python
   - Add license: MIT (or your choice)

3. **Clone to Local:**
```bash
git clone https://github.com/YOUR_USERNAME/JAKAL.git
cd JAKAL
```

4. **Generate SSH Deploy Key:**
   - Settings → Deploy keys → Add deploy key
   - Title: `oracle-production`
   - Key: `cat ~/.ssh/id_rsa.pub` (or generate new with `ssh-keygen`)
   - Allow write access: ✅ (for CI/CD pushes)

5. **Add GitHub Secrets (for CI/CD):**
   - Settings → Secrets and variables → Actions → New repository secret
   - Add each secret:
     - `ORACLE_INSTANCE_IP`
     - `ORACLE_SSH_KEY`
     - `DOCKERHUB_USER`
     - `DOCKERHUB_TOKEN`
     - `GEMINI_API_KEY` (base64 encoded)
     - `IBM_QUANTUM_TOKEN` (base64 encoded)
     - etc.

### Save to Credentials Vault
```
GITHUB_REPO=https://github.com/YOUR_USERNAME/JAKAL.git
GITHUB_SSH_DEPLOY_KEY_PATH=./github_deploy_key
```

---

## Account 7: Vercel (Frontend Hosting)

### Why Vercel?
- Next.js/React deployment
- Automatic deployments on git push
- Global CDN edge distribution
- $0/month for free tier

### Setup Steps

1. **Visit:** https://vercel.com/
2. **Sign Up with GitHub:**
   - Click: "Continue with GitHub"
   - Authorize Vercel

3. **Import JAKAL Repository:**
   - Click: "Import Project"
   - Select: Your JAKAL GitHub repo
   - Configure:
     - Framework: React (or None if static HTML)
     - Root directory: `frontend/`
     - Build command: `npm run build`
     - Output directory: `dist/`

4. **Environment Variables:**
   - Add:
     - `VITE_API_URL=https://api.jakal.your-domain.com`
     - `VITE_WEBSOCKET_URL=wss://api.jakal.your-domain.com/ws`

5. **Deploy** (auto-triggers on git push to main)

### Save to Credentials Vault
```
VERCEL_PROJECT_NAME=jakal
VERCEL_PROJECT_ID=...
VERCEL_TEAM_ID=... (if using team)
VERCEL_DEPLOYMENT_TOKEN=... (for API access)
```

---

## Account 8: DockerHub (Container Registry)

### Why DockerHub?
- Container image hosting
- Public (free) and private repos
- Integration with GitHub
- $0/month for free tier

### Setup Steps

1. **Visit:** https://hub.docker.com/
2. **Sign Up:**
   - Email or Docker account
   - Verify email

3. **Create Repository:**
   - Click: "Repositories" → "Create repository"
   - Name: `jakal-backend`
   - Description: `JAKAL Enterprise Penetration Testing Backend`
   - Visibility: Public
   - Create

4. **Generate Access Token:**
   - Account settings (top-right) → Security
   - Click: "New Access Token"
   - Description: `github-actions`
   - Permissions: Read, Write, Delete
   - Copy token (save securely)

5. **Connect GitHub:**
   - Repository settings → Build settings
   - Connect GitHub account
   - Select: `YOUR_USERNAME/JAKAL`
   - Build rules: Push to `main` → Build `latest`

### Save to Credentials Vault
```
DOCKERHUB_USERNAME=your_username
DOCKERHUB_TOKEN=...
DOCKERHUB_REPO=your_username/jakal-backend
```

---

## Account 9: Shodan (OSINT Reconnaissance)

### Why Shodan?
- Search engine for internet-connected devices
- Essential for reconnaissance phase
- Free tier: 1 query/month (or ~$50/month for unlimited)
- For MVP: Use free tier or pay for one month

### Setup Steps

1. **Visit:** https://www.shodan.io/
2. **Sign Up:**
   - Email address
   - Password
   - Verify email

3. **API Key:**
   - Account → Settings
   - API key: Copy (shows on page)

4. **Optional - Paid Plan for Testing:**
   - Plans → Plus ($49/month, cancel anytime)
   - Enables: 100+ queries/month, historical data, more details
   - For MVP: Consider for first month of development

### Save to Credentials Vault
```
SHODAN_API_KEY=...
SHODAN_PLAN=free  # or 'plus'
```

---

## Summary: Create Credentials Vault File

Create file: `backend/.env` (NEVER commit to git)

```bash
cat > backend/.env << 'EOF'
# ORACLE CLOUD
ORACLE_INSTANCE_IP=YOUR_IP_HERE
ORACLE_SSH_KEY_PATH=./oracle_key.pem
ORACLE_USERNAME=ubuntu

# SUPABASE
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...
SUPABASE_DB_PASSWORD=...
DATABASE_URL=postgresql://...

# FIREBASE
FIREBASE_PROJECT_ID=jakal-auth-abc123
FIREBASE_WEB_API_KEY=AIza...
FIREBASE_SERVICE_ACCOUNT_KEY=./firebase-service-account.json

# GOOGLE GEMINI
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-1.5-flash

# IBM QUANTUM
IBM_QUANTUM_TOKEN=...
IBM_QUANTUM_INSTANCE=ibm-q/open/main

# GITHUB
GITHUB_REPO=https://github.com/YOUR_USERNAME/JAKAL.git
GITHUB_TOKEN=... (for deployments)

# VERCEL
VERCEL_PROJECT_NAME=jakal
VERCEL_DEPLOYMENT_TOKEN=...

# DOCKERHUB
DOCKERHUB_USERNAME=your_username
DOCKERHUB_TOKEN=...
DOCKERHUB_REPO=your_username/jakal-backend

# SHODAN
SHODAN_API_KEY=...

# APPLICATION
ENVIRONMENT=production
LOG_LEVEL=INFO
API_PORT=8000
ALLOWED_ORIGINS=https://jakal.vercel.app,https://jakal.your-domain.com,http://localhost:3000
EOF

# Add to .gitignore
echo "backend/.env" >> .gitignore
echo "*.pem" >> .gitignore
echo "*-service-account.json" >> .gitignore
```

### Add to `.gitignore`
```
# Credentials (NEVER commit)
.env
.env.local
*.pem
*-service-account.json
*-credentials.json

# IDE
.vscode/
.idea/

# Build
node_modules/
dist/
build/
*.egg-info/

# Database
*.duckdb
*.db

# Logs
logs/
*.log

# OS
.DS_Store
Thumbs.db
```

---

## Verification Checklist ✅

- [ ] Oracle Cloud instance running (can SSH into it)
- [ ] Supabase project created (URL & API keys saved)
- [ ] Firebase project created (service account JSON saved)
- [ ] Google Gemini API key obtained & tested
- [ ] IBM Quantum token created & tested
- [ ] GitHub repository created & cloned locally
- [ ] Vercel project connected to GitHub
- [ ] DockerHub repository created & token generated
- [ ] Shodan API key obtained
- [ ] `.env` file created with all credentials
- [ ] `.gitignore` includes `.env` and credential files
- [ ] All credentials saved in secure vault (e.g., 1Password, Bitwarden, or local encrypted file)

**CRITICAL REMINDERS:**
- **Never commit `.env`, `*.pem`, or `*-service-account.json` to git**
- **Store credentials in secure password manager**
- **Rotate tokens monthly**
- **Enable 2FA on all accounts**

---

## Next Steps

Once Phase 0 is complete:
1. Proceed to **Phase 1: Core Backend Infrastructure & Database Schema**
2. Initialize local development environment
3. Create DuckDB schema
4. Build FastAPI foundation

