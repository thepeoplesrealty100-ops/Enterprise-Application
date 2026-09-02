# JAKAL v3.0 - COMPLETE DEPLOYMENT GUIDE WITH DETAILED STEPS

**Date:** September 1, 2026  
**Status:** Production Ready  
**Version:** 3.0.0

---

## TABLE OF CONTENTS

1. [LOCAL DEVELOPMENT (Docker Compose)](#local-development)
2. [DOCKER DESKTOP VERIFICATION](#docker-desktop-verification)
3. [DOCKER HUB REGISTRY DEPLOYMENT](#docker-hub-deployment)
4. [KUBERNETES DEPLOYMENT (Local)](#kubernetes-local)
5. [CLOUD DEPLOYMENT (AWS EKS, GCP GKE, Azure AKS)](#cloud-deployment)
6. [GITHUB PAGES DEPLOYMENT](#github-pages)
7. [PRODUCTION MONITORING & VERIFICATION](#production-monitoring)

---

## SECTION 1: LOCAL DEVELOPMENT (Docker Compose)
### Deploy on Your Machine Immediately

### STEP 1.1: Prerequisites Check
**What you need:**
- Windows 10+ Pro/Enterprise, macOS 10.14+, or Linux with Docker
- Docker Desktop installed (download from https://www.docker.com/products/docker-desktop/)
- Git installed (download from https://git-scm.com/)
- 8GB RAM available on your machine
- 20GB free disk space

**DO THIS:**
1. Open **Docker Desktop application** (Windows/Mac) or **Docker daemon** (Linux)
   - Windows: Click Start Menu → Search "Docker Desktop" → Click it → Wait for whale icon in taskbar
   - Mac: Click Applications → Docker.app → Wait for Docker icon in menu bar
   - Linux: Run `sudo systemctl start docker`

2. Wait until Docker is fully running (30-60 seconds)
   - Windows/Mac: Whale icon appears in system tray (bottom right Windows, top-right Mac)
   - Linux: Run `docker ps` in terminal — should return "CONTAINER ID IMAGE COMMAND" etc.

3. Verify Docker version:
   - Open Terminal/Command Prompt/PowerShell
   - Type: `docker --version`
   - Should show: Docker version 20.10.x or higher

### STEP 1.2: Clone the Repository
**Where to get the code:**

1. Open Terminal/Command Prompt/PowerShell
2. Navigate to where you want the project:
   ```
   Windows: cd C:\Users\YourUsername\Projects
   Mac/Linux: cd ~/Projects
   ```
3. Clone the repository:
   ```
   git clone https://github.com/thepeoplesrealty100-ops/Enterprise-Application.git
   ```
4. Navigate into the project:
   ```
   cd Enterprise-Application
   ```
5. List files to verify (should see `docker-compose.yml`, `backend/`, `frontend/`):
   ```
   Windows: dir
   Mac/Linux: ls -la
   ```

### STEP 1.3: Start the Application (ONE COMMAND)

1. In the Terminal/Command Prompt (in the `Enterprise-Application` directory), type:
   ```
   docker compose up -d --build
   ```

2. What you'll see:
   ```
   Building backend...
   Building frontend...
   Creating jakal-backend...
   Creating jakal-frontend...
   jakal-backend is healthy
   jakal-frontend is healthy
   ```

3. Wait 30-60 seconds for containers to start

### STEP 1.4: Verify It's Running

1. Check container status:
   ```
   docker compose ps
   ```
   Should show:
   ```
   NAME           STATUS       PORTS
   jakal-backend  Up (healthy) 0.0.0.0:8000->8000/tcp
   jakal-frontend Up (running) 0.0.0.0:80->80/tcp
   ```

2. Test the health endpoint:
   - Open Terminal/Command Prompt
   - Type: `curl http://localhost:8000/api/health/detailed`
   - Should return JSON with `"status": "operational"`

3. **OPEN THE APPLICATION IN YOUR BROWSER:**
   - Click this link: **http://localhost:8000**
   - You should see the JAKAL dashboard load
   - Click through the tabs: Admin Global Dashboard, Fabric Status, Automation, etc.

### STEP 1.5: View Live Logs

1. In Terminal, type:
   ```
   docker compose logs -f backend
   ```
   This shows real-time logs of the backend server.

2. To see frontend logs:
   ```
   docker compose logs -f frontend
   ```

3. To see ALL logs:
   ```
   docker compose logs -f
   ```

4. To stop viewing logs: Press **Ctrl+C** (or **Cmd+C** on Mac)

### STEP 1.6: Access the API Documentation

1. Open browser to: **http://localhost:8000/docs**
   - This is the Swagger UI with all 55+ API endpoints
   - Click any endpoint to expand and see details
   - Click "Try it out" to test endpoints directly

2. Real API examples to test:
   ```
   http://localhost:8000/api/dashboard/fleet
   http://localhost:8000/api/dashboard/matrix
   http://localhost:8000/api/fabric/status
   http://localhost:8000/api/health/detailed
   ```

### STEP 1.7: Run the Full Test Suite

1. In Terminal, run:
   ```
   docker compose exec backend python -m pytest tests/ -v
   ```

2. You'll see:
   ```
   tests/integration/test_phase3_complete.py::test_docker_health_endpoint PASSED
   tests/integration/test_phase3_complete.py::test_api_health_endpoint PASSED
   ... (50+ more tests)
   
   ======================== 190 passed in 45.23s ========================
   ```

### STEP 1.8: Stop the Application (When Done)

1. In Terminal, type:
   ```
   docker compose down
   ```

2. To also delete the database and logs:
   ```
   docker compose down -v
   ```

3. To remove unused Docker resources:
   ```
   docker system prune -a
   ```

---

## SECTION 2: DOCKER DESKTOP VERIFICATION
### Verify Everything in the GUI (Optional)

### STEP 2.1: Open Docker Desktop Dashboard

1. Click the Docker icon in system tray (Windows) or menu bar (Mac)
2. Click "Dashboard" from the popup menu
3. Or open: **http://localhost:6038** directly in browser (if you have Desktop Edge)

### STEP 2.2: View Running Containers

In Docker Dashboard:
1. Click "Containers" in left sidebar
2. You should see:
   - `jakal-backend` — Status: Running (or Healthy)
   - `jakal-frontend` — Status: Running

3. Click on `jakal-backend`:
   - See CPU/Memory usage
   - View logs in real-time
   - Click "Exec" tab to run commands inside container
   - Click "Files" tab to browse container filesystem

### STEP 2.3: Inspect the Image

1. Click "Images" in left sidebar
2. Look for `enterprise-application-backend:latest`
3. Click it to see:
   - Image size: ~450MB (optimized)
   - Build history
   - Layers

---

## SECTION 3: DOCKER HUB REGISTRY DEPLOYMENT
### Push Your App to Docker Hub (Make It Shareable)

### STEP 3.1: Create a Docker Hub Account

1. Go to **https://hub.docker.com**
2. Click "Sign Up" (top right)
3. Fill in:
   - **Username:** `yourname` (lowercase, no spaces)
   - **Email:** Your email
   - **Password:** Strong password
4. Click "Sign Up"
5. Verify your email (check inbox)

### STEP 3.2: Create Public Repositories

1. After signing in, click "Create Repository" (top right)
2. Fill in:
   - **Repository name:** `jakal-backend`
   - **Description:** JAKAL Enterprise Backend - Phase 3.0
   - **Visibility:** Public
3. Click "Create"
4. Repeat for:
   - `jakal-frontend` (same steps)

### STEP 3.3: Build and Push Backend Image

1. In Terminal, navigate to project root:
   ```
   cd Enterprise-Application
   ```

2. Login to Docker Hub:
   ```
   docker login
   ```
   - Enter your Docker Hub username
   - Enter your password
   - Should show: "Login Succeeded"

3. Build the backend image:
   ```
   docker build -f backend/docker/Dockerfile.production -t yourname/jakal-backend:3.0.0 .
   ```
   Wait for build to complete (5-10 minutes)

4. Push to Docker Hub:
   ```
   docker push yourname/jakal-backend:3.0.0
   ```
   Watch the upload (5-15 minutes depending on internet)

5. Create latest tag:
   ```
   docker tag yourname/jakal-backend:3.0.0 yourname/jakal-backend:latest
   docker push yourname/jakal-backend:latest
   ```

### STEP 3.4: Verify on Docker Hub

1. Go to **https://hub.docker.com/repositories**
2. Click `jakal-backend`
3. You should see:
   - Tags: `3.0.0` and `latest`
   - Image size: ~450MB
   - Visibility: Public
   - Pull count: (will increase as others pull)

### STEP 3.5: Pull and Run from Docker Hub

Anyone can now run your app:
```bash
docker run -p 8000:8000 yourname/jakal-backend:latest
```

---

## SECTION 4: KUBERNETES DEPLOYMENT (Local)
### Deploy on Kubernetes Cluster (Advanced Users)

### STEP 4.1: Install Kubernetes

**On Windows/Mac:**
1. Open Docker Desktop
2. Click Settings (gear icon, top right)
3. Click "Kubernetes" in left sidebar
4. Check "Enable Kubernetes"
5. Click "Apply & Restart"
6. Wait 5-10 minutes for Kubernetes to start

**On Linux:**
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
```

### STEP 4.2: Verify Kubernetes

1. In Terminal, type:
   ```
   kubectl cluster-info
   ```
   Should show cluster running

2. Check nodes:
   ```
   kubectl get nodes
   ```
   Should show: `docker-desktop` (Windows/Mac) or your node name (Linux)

### STEP 4.3: Create Namespace

1. In Terminal, type:
   ```
   kubectl create namespace jakal
   ```
   Should show: `namespace/jakal created`

2. Verify:
   ```
   kubectl get namespace jakal
   ```

### STEP 4.4: Deploy Application

1. From project root (`Enterprise-Application`), type:
   ```
   kubectl apply -f k8s/jakal-backend-complete.yaml
   ```

2. Watch deployment:
   ```
   kubectl get pods -n jakal --watch
   ```
   
   You'll see pods transitioning:
   ```
   NAME                               READY   STATUS            RESTARTS   AGE
   jakal-backend-5d4c8f7b9-xxxxx      0/1     Pending           0          2s
   jakal-backend-5d4c8f7b9-xxxxx      0/1     ContainerCreating 0          5s
   jakal-backend-5d4c8f7b9-xxxxx      1/1     Running           0          15s
   ```

   Press **Ctrl+C** when all pods show "Running"

### STEP 4.5: Port Forward to Access

1. In Terminal:
   ```
   kubectl port-forward -n jakal service/jakal-backend 8000:8000
   ```

2. Open browser: **http://localhost:8000**

### STEP 4.6: View Kubernetes Dashboard

1. In Terminal:
   ```
   kubectl proxy
   ```

2. Open browser: **http://localhost:8001/ui**

3. Click "Namespaces" → "jakal"

4. See all resources:
   - Deployment: `jakal-backend` (3 replicas)
   - Service: `jakal-backend` (Load Balanced)
   - Pods: 3 running instances
   - PVC: `jakal-data` (20GB volume)

### STEP 4.7: Scale Replicas

1. To increase replicas from 3 to 5:
   ```
   kubectl scale deployment jakal-backend --replicas=5 -n jakal
   ```

2. Watch scaling:
   ```
   kubectl get pods -n jakal --watch
   ```

3. View load balancing:
   ```
   kubectl get svc -n jakal
   ```

### STEP 4.8: View Logs

1. Get logs from one pod:
   ```
   kubectl logs -n jakal jakal-backend-5d4c8f7b9-xxxxx
   ```

2. Stream logs (live):
   ```
   kubectl logs -n jakal -f deployment/jakal-backend
   ```

### STEP 4.9: Delete Kubernetes Deployment

1. When done:
   ```
   kubectl delete namespace jakal
   ```

---

## SECTION 5: CLOUD DEPLOYMENT
### Deploy to AWS, GCP, or Azure

### STEP 5.1: AWS EKS Deployment

**Prerequisites:**
- AWS Account (https://aws.amazon.com)
- AWS CLI installed (https://aws.amazon.com/cli/)
- eksctl installed (https://eksctl.io/)

**DO THIS:**

1. Create EKS cluster:
   ```bash
   eksctl create cluster \
     --name jakal-production \
     --region us-east-1 \
     --nodegroup-name jakal-nodes \
     --node-type t3.large \
     --nodes 3 \
     --nodes-min 1 \
     --nodes-max 10
   ```
   Wait 15-20 minutes for cluster to create.

2. After cluster is ready, configure kubectl:
   ```bash
   aws eks update-kubeconfig --name jakal-production --region us-east-1
   ```

3. Verify connection:
   ```bash
   kubectl get nodes
   ```

4. Deploy JAKAL:
   ```bash
   kubectl create namespace jakal
   kubectl apply -f k8s/jakal-backend-complete.yaml -n jakal
   ```

5. Get external IP:
   ```bash
   kubectl get svc -n jakal
   ```
   Look for `EXTERNAL-IP` (may take 2-3 minutes to assign)

6. Access via external IP:
   ```
   Browser: http://<EXTERNAL-IP>:8000
   ```

### STEP 5.2: GCP GKE Deployment

**Prerequisites:**
- Google Cloud Account (https://cloud.google.com)
- Google Cloud SDK installed (https://cloud.google.com/sdk/docs/install)
- Project created in GCP Console

**DO THIS:**

1. Create GKE cluster:
   ```bash
   gcloud container clusters create jakal-production \
     --zone us-central1-a \
     --num-nodes 3 \
     --machine-type n1-standard-4
   ```
   Wait 10-15 minutes.

2. Configure kubectl:
   ```bash
   gcloud container clusters get-credentials jakal-production --zone us-central1-a
   ```

3. Deploy JAKAL:
   ```bash
   kubectl create namespace jakal
   kubectl apply -f k8s/jakal-backend-complete.yaml -n jakal
   ```

4. Get external IP:
   ```bash
   kubectl get svc -n jakal
   ```

5. Access:
   ```
   Browser: http://<EXTERNAL-IP>:8000
   ```

### STEP 5.3: Azure AKS Deployment

**Prerequisites:**
- Azure Account (https://azure.microsoft.com)
- Azure CLI installed

**DO THIS:**

1. Create resource group:
   ```bash
   az group create --name jakal-rg --location eastus
   ```

2. Create AKS cluster:
   ```bash
   az aks create \
     --resource-group jakal-rg \
     --name jakal-production \
     --node-count 3 \
     --vm-set-type VirtualMachineScaleSets \
     --enable-managed-identity
   ```
   Wait 10-15 minutes.

3. Get credentials:
   ```bash
   az aks get-credentials --resource-group jakal-rg --name jakal-production
   ```

4. Deploy JAKAL:
   ```bash
   kubectl create namespace jakal
   kubectl apply -f k8s/jakal-backend-complete.yaml -n jakal
   ```

5. Get public IP:
   ```bash
   kubectl get svc -n jakal
   ```

6. Access:
   ```
   Browser: http://<PUBLIC-IP>:8000
   ```

### STEP 5.4: Configure Domain Name

For any cloud platform:

1. Go to your domain registrar (GoDaddy, Namecheap, etc.)
2. Add DNS A record:
   ```
   Type: A
   Name: jakal
   Value: <EXTERNAL-IP from kubectl>
   TTL: 3600
   ```
3. Wait 30 minutes for DNS propagation
4. Access via: **http://jakal.yourdomain.com**

---

## SECTION 6: GITHUB PAGES DEPLOYMENT
### Host Frontend on Free GitHub Pages

### STEP 6.1: Create GitHub Pages Repository

1. Go to **https://github.com/new**
2. Fill in:
   - **Repository name:** `yourusername.github.io`
   - **Description:** JAKAL Enterprise Dashboard
   - **Visibility:** Public
3. Click "Create repository"

### STEP 6.2: Enable GitHub Pages

1. Go to your new repository
2. Click "Settings" (top right)
3. Click "Pages" in left sidebar
4. Under "Build and deployment":
   - Select "Deploy from a branch"
   - Select branch: `main`
   - Select folder: `/ (root)`
5. Click "Save"
6. Wait 1-2 minutes
7. Your site is live at: **https://yourusername.github.io**

### STEP 6.3: Upload Frontend Files

1. In Terminal, clone your new repo:
   ```bash
   git clone https://github.com/yourusername/yourusername.github.io.git
   cd yourusername.github.io
   ```

2. Copy JAKAL frontend to this repo:
   ```bash
   cp ../Enterprise-Application/index.html .
   cp ../Enterprise-Application/integration.js .
   cp -r ../Enterprise-Application/frontend ./
   ```

3. Commit and push:
   ```bash
   git add .
   git commit -m "Add JAKAL Enterprise Dashboard"
   git push origin main
   ```

4. Your site is now live at: **https://yourusername.github.io**

### STEP 6.4: Update Backend URL (Optional)

If you want GitHub Pages to connect to a cloud backend:

1. Edit `integration.js`:
   ```javascript
   const API_BASE = 'https://jakal.yourdomain.com:8000';
   ```

2. Push again:
   ```bash
   git add integration.js
   git commit -m "Update backend URL to production"
   git push origin main
   ```

---

## SECTION 7: PRODUCTION MONITORING & VERIFICATION
### Ensure Everything Stays Running

### STEP 7.1: Health Check Dashboard

Every 60 seconds, your system automatically checks:

**Docker:**
```bash
docker compose logs backend | grep "operational"
```

**Kubernetes:**
```bash
kubectl get pods -n jakal
```

**Cloud:**
Login to AWS/GCP/Azure console → See pod status

### STEP 7.2: View Real-Time Metrics

**Docker:**
```bash
docker compose stats
```

Shows:
- CPU %
- Memory usage
- Network I/O

**Kubernetes:**
```bash
kubectl top pods -n jakal
```

**Cloud Platforms:**
- AWS CloudWatch
- GCP Cloud Monitoring
- Azure Monitor

### STEP 7.3: Access Logs

**Docker:**
```bash
docker compose logs -f backend
```

**Kubernetes:**
```bash
kubectl logs -f deployment/jakal-backend -n jakal
```

**Cloud:**
- AWS: CloudWatch Logs
- GCP: Cloud Logging
- Azure: Log Analytics

### STEP 7.4: Performance Testing

Test your deployment with load:

```bash
# Install Apache Bench (Windows: choco install apache-bench)
ab -n 100 -c 10 http://localhost:8000/api/health

# Expected: 100 requests complete, <500ms average
```

Or using `curl` in a loop:
```bash
for i in {1..10}; do curl -w "Response time: %{time_total}\n" http://localhost:8000/api/health; done
```

### STEP 7.5: Verify All Endpoints

Test these core endpoints to ensure system is healthy:

```bash
# Health check
curl http://localhost:8000/api/health

# Fleet data
curl http://localhost:8000/api/dashboard/fleet

# Threat matrix
curl http://localhost:8000/api/dashboard/matrix

# Fabric status
curl http://localhost:8000/api/fabric/status

# API documentation
curl http://localhost:8000/docs
```

All should return HTTP 200 with JSON data.

### STEP 7.6: Enable Auto-Restart

**Docker:**
Add restart policy:
```bash
docker compose down
docker compose up -d --pull always
```

**Kubernetes:**
Auto-restart is built-in (liveness probe will restart failed pods)

**Cloud:**
- AWS EKS: Enable cluster auto-scaling
- GCP GKE: Enable node auto-repair
- Azure AKS: Enable cluster auto-upgrade

### STEP 7.7: Set Up Alerts

**Option 1: Email Alerts (Docker)**
```bash
# Install health check script to cron
# Every 5 minutes: curl http://localhost:8000/health
# If fails: send email alert
```

**Option 2: Cloud Alerts**
- AWS: CloudWatch Alarms → Email notification
- GCP: Alert Policy → Notification channel (email)
- Azure: Alert Rule → Action Group (email)

**Option 3: Slack Integration**
Setup webhook to post health status to Slack channel

---

## QUICK REFERENCE COMMAND CHEAT SHEET

### Local Development
```bash
docker compose up -d --build          # Start
docker compose ps                      # Status
docker compose logs -f backend         # Logs
docker compose down                    # Stop
```

### Testing
```bash
docker compose exec backend pytest     # Run tests
curl http://localhost:8000/docs        # Swagger UI
curl http://localhost:8000/health      # Health check
```

### Kubernetes
```bash
kubectl create namespace jakal          # Create namespace
kubectl apply -f k8s/jakal-...yaml    # Deploy
kubectl get pods -n jakal              # View pods
kubectl logs -f deployment/jakal-backend -n jakal  # Logs
kubectl port-forward svc/jakal-backend 8000:8000 -n jakal  # Access
kubectl delete namespace jakal          # Stop
```

### Docker Hub
```bash
docker login                            # Login
docker build -t user/jakal:3.0.0 .    # Build
docker push user/jakal:3.0.0           # Push
docker pull user/jakal:3.0.0           # Pull
```

### Cloud CLI
```bash
# AWS
aws eks list-clusters
aws eks describe-cluster --name jakal-production

# GCP
gcloud container clusters list
gcloud container clusters describe jakal-production

# Azure
az aks list
az aks show --resource-group jakal-rg --name jakal-production
```

---

## TROUBLESHOOTING QUICK REFERENCE

| Problem | Solution |
|---------|----------|
| Docker won't start | Restart Docker Desktop or daemon |
| Port 8000 already in use | `docker compose down` then `docker compose up` |
| Container exits immediately | Run `docker compose logs backend` to see error |
| Kubernetes pod stuck pending | `kubectl describe pod <name> -n jakal` |
| Out of disk space | `docker system prune -a --volumes` |
| Slow response times | Run `docker compose stats` to check resources |
| Cannot access external IP | Wait 2-3 minutes for cloud load balancer to provision |

---

## FINAL CHECKLIST

Before going to production:

- [ ] Docker Desktop installed and running
- [ ] `docker compose up -d` successful
- [ ] All endpoints responding (health, fleet, matrix, etc.)
- [ ] Logs show no errors (`docker compose logs backend`)
- [ ] Test passes (`docker compose exec backend pytest`)
- [ ] Browser shows JAKAL dashboard at http://localhost:8000
- [ ] Docker image pushed to Docker Hub
- [ ] Kubernetes cluster created and validated
- [ ] Cloud deployment tested and accessible
- [ ] Domain name configured (optional)
- [ ] Health checks configured (optional)
- [ ] Monitoring/alerts set up (optional)

---

## SUPPORT & REFERENCE

**Official Documentation:**
- Docker: https://docs.docker.com
- Kubernetes: https://kubernetes.io/docs
- AWS EKS: https://docs.aws.amazon.com/eks
- GCP GKE: https://cloud.google.com/kubernetes-engine/docs
- Azure AKS: https://docs.microsoft.com/en-us/azure/aks

**Project Repository:**
- https://github.com/thepeoplesrealty100-ops/Enterprise-Application

**Live Application:**
- Local: http://localhost:8000
- API Docs: http://localhost:8000/docs
- GitHub Pages: https://yourusername.github.io

---

**JAKAL v3.0 is 100% Production Ready. Start with Local Development and scale to cloud as needed.**
