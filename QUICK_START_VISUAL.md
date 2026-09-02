# JAKAL v3.0 - VISUAL DEPLOYMENT QUICK-START
## Exact Clicks and Actions for Non-Technical Users

---

## OPTION A: DEPLOY LOCALLY IN 5 MINUTES

### Step 1: Download Docker Desktop
1. Open web browser
2. Go to: **https://www.docker.com/products/docker-desktop**
3. Click blue "Download" button
4. Select your system:
   - Windows → Download installer
   - Mac → Download Intel or Apple Silicon version
   - Linux → Follow instructions
5. Run the installer and follow prompts
6. Restart your computer when finished

### Step 2: Download Your Project
1. Open web browser
2. Go to: **https://github.com/thepeoplesrealty100-ops/Enterprise-Application**
3. Click green "Code" button (top right)
4. Click "Download ZIP"
5. Extract the ZIP file to your Documents or Desktop folder
6. Rename folder to: `Enterprise-Application` (remove -main if present)

### Step 3: Open Command Line
**Windows:**
1. Press `Windows Key + R`
2. Type: `cmd`
3. Press Enter
4. Terminal window opens

**Mac:**
1. Press `Command + Space`
2. Type: `terminal`
3. Press Enter
4. Terminal window opens

**Linux:**
1. Right-click desktop
2. Click "Open Terminal Here"
3. Terminal window opens

### Step 4: Navigate to Your Project
In the terminal, type:
```
cd Documents/Enterprise-Application
```
(Or wherever you extracted the folder)

### Step 5: Start the Application (THE KEY COMMAND)
In the terminal, type:
```
docker compose up -d --build
```
Press Enter.

**What you'll see:**
```
Building backend image...
Building frontend image...
Creating jakal-backend...
jakal-backend is healthy
Creating jakal-frontend...
jakal-frontend is healthy
```

Wait 30-60 seconds.

### Step 6: Open Application in Browser
1. Open your web browser (Chrome, Firefox, Safari, Edge)
2. Type in address bar: **http://localhost:8000**
3. Press Enter

**YOU SHOULD NOW SEE THE JAKAL DASHBOARD**

---

## OPTION B: DEPLOY WITH ONE CLICK (WINDOWS ONLY)

### Create a Batch File
1. Open Notepad
2. Paste this:
```batch
@echo off
cd %~dp0
docker compose up -d --build
echo.
echo =========================================
echo JAKAL Application Starting...
echo =========================================
echo.
echo Wait 30 seconds, then open:
echo http://localhost:8000
echo.
pause
```
3. Save as: `START_JAKAL.bat` (in your project folder)
4. Double-click `START_JAKAL.bat` to start everything

---

## OPTION C: DOCKER DESKTOP VISUAL GUIDE

### View Running Containers in GUI
1. Click Docker icon in system tray (bottom right Windows, top-right Mac)
2. Click "Dashboard" from menu
3. You should see:
   - `jakal-backend` — Status: Running
   - `jakal-frontend` — Status: Running

### Click on `jakal-backend` to:
- **View Logs:** Click "Logs" tab
- **Stop Container:** Right-click → "Stop"
- **View CPU/Memory:** See live metrics
- **Run Commands:** Click "Exec" tab

### Right-click `jakal-backend` to:
- View logs
- Stop/restart
- Remove container
- Inspect details

---

## OPTION D: PUSH TO DOCKER HUB (MAKE IT SHAREABLE)

### Step 1: Create Docker Hub Account
1. Open browser to: **https://hub.docker.com**
2. Click "Sign Up" (top right)
3. Fill in:
   - Username: `yourname` (lowercase)
   - Email: your@email.com
   - Password: strong password
4. Click "Sign Up"
5. Verify email (check your inbox)

### Step 2: Create Repositories
1. After login, click "Create Repository" (or "+" icon)
2. For backend:
   - Name: `jakal-backend`
   - Description: JAKAL Backend
   - Visibility: **Public**
   - Click "Create"
3. Repeat for `jakal-frontend`

### Step 3: Login via Terminal
1. Open terminal
2. Type: `docker login`
3. Enter your Docker Hub username
4. Enter your password
5. Press Enter
6. Should show: "Login Succeeded"

### Step 4: Push Your Images
In terminal, type:
```
docker push yourname/jakal-backend:latest
docker push yourname/jakal-frontend:latest
```

Wait for upload to complete (5-15 minutes).

### Step 5: Verify on Docker Hub
1. Go to: **https://hub.docker.com/repositories**
2. You should see your `jakal-backend` and `jakal-frontend` repositories
3. Click on one to see pull command
4. Share pull command with others: `docker pull yourname/jakal-backend`

---

## OPTION E: DEPLOY TO KUBERNETES (LOCAL)

### Step 1: Enable Kubernetes in Docker Desktop

**Windows/Mac:**
1. Click Docker icon → "Settings" (gear icon)
2. Click "Kubernetes" in left sidebar
3. Check box: "Enable Kubernetes"
4. Click "Apply & Restart"
5. Wait 5-10 minutes while Kubernetes starts

**Indicator:** Whale icon shows "Kubernetes is running"

### Step 2: Open Terminal
1. Windows: `Windows Key + R` → type `cmd`
2. Mac: `Command + Space` → type `terminal`
3. Linux: Open terminal

### Step 3: Create Namespace
Type in terminal:
```
kubectl create namespace jakal
```

### Step 4: Deploy Application
In project folder, type:
```
kubectl apply -f k8s/jakal-backend-complete.yaml
```

### Step 5: Wait for Deployment
Type:
```
kubectl get pods -n jakal --watch
```

Watch until you see:
```
NAME                           READY   STATUS
jakal-backend-xxxxx-xxxxx      1/1     Running
jakal-backend-xxxxx-xxxxx      1/1     Running
jakal-backend-xxxxx-xxxxx      1/1     Running
```

Press `Ctrl+C` to stop watching.

### Step 6: Access Application
Type:
```
kubectl port-forward -n jakal service/jakal-backend 8000:8000
```

Open browser to: **http://localhost:8000**

---

## OPTION F: DEPLOY TO AWS CLOUD

### Step 1: Create AWS Account
1. Go to: **https://aws.amazon.com**
2. Click "Create an AWS Account" (top right)
3. Enter your email, choose a password
4. Complete the signup process
5. Add payment method

### Step 2: Install AWS CLI
1. Go to: **https://aws.amazon.com/cli/**
2. Click "Download" and follow instructions for your system
3. Install it

### Step 3: Configure AWS Access
1. Go to AWS Console: **https://console.aws.amazon.com**
2. Click your account name (top right) → "My Security Credentials"
3. Click "Create access key"
4. Download CSV file (save it safely)
5. In terminal:
   ```
   aws configure
   ```
6. Enter:
   - Access Key ID (from CSV)
   - Secret Access Key (from CSV)
   - Region: `us-east-1`

### Step 4: Create EKS Cluster
Install eksctl: **https://eksctl.io/**

In terminal:
```
eksctl create cluster --name jakal-prod --region us-east-1 --nodegroup-name jakal-nodes --node-type t3.large --nodes 3
```

Wait 15-20 minutes.

### Step 5: Deploy JAKAL
```
kubectl apply -f k8s/jakal-backend-complete.yaml
```

### Step 6: Get External IP
```
kubectl get svc
```

Copy the EXTERNAL-IP value and open in browser: **http://<EXTERNAL-IP>:8000**

---

## OPTION G: DEPLOY TO GCP CLOUD

### Step 1: Create Google Cloud Account
1. Go to: **https://cloud.google.com**
2. Click "Get started for free"
3. Sign in with Google account
4. Setup billing

### Step 2: Create Project
1. Open GCP Console: **https://console.cloud.google.com**
2. Click "Select a project" (top left)
3. Click "New Project"
4. Name: `JAKAL`
5. Click "Create"

### Step 3: Enable GKE API
1. In GCP Console, click search bar (top)
2. Search: `GKE`
3. Click "Google Kubernetes Engine"
4. Click "Enable API" if not already enabled

### Step 4: Create GKE Cluster
1. Click "Create Cluster"
2. Fill in:
   - Name: `jakal-production`
   - Zone: `us-central1-a`
   - Nodes: `3`
3. Click "Create"

Wait 10-15 minutes.

### Step 5: Deploy JAKAL
1. Click cluster name when ready
2. Click "Connect" (top right)
3. Copy the command shown
4. Paste into terminal
5. In terminal, run:
   ```
   kubectl apply -f k8s/jakal-backend-complete.yaml
   ```

### Step 6: Access Application
```
kubectl get svc
```

Copy EXTERNAL-IP and open: **http://<EXTERNAL-IP>:8000**

---

## OPTION H: DEPLOY TO AZURE CLOUD

### Step 1: Create Azure Account
1. Go to: **https://azure.microsoft.com**
2. Click "Start free"
3. Sign in or create account
4. Complete signup

### Step 2: Create Resource Group
1. Open Azure Portal: **https://portal.azure.com**
2. Search for "Resource groups"
3. Click "Create"
4. Fill in:
   - Resource group: `jakal-rg`
   - Region: `East US`
5. Click "Create"

### Step 3: Create AKS Cluster
1. Search for "Kubernetes Services"
2. Click "Create"
3. Fill in:
   - Name: `jakal-production`
   - Resource group: `jakal-rg`
   - Node count: `3`
4. Click "Review + create" → "Create"

Wait 10-15 minutes.

### Step 4: Get Connection String
1. Go to your cluster
2. Click "Overview" tab
3. Click "Connect" button
4. Copy the commands
5. Paste into terminal

### Step 5: Deploy JAKAL
```
kubectl apply -f k8s/jakal-backend-complete.yaml
```

### Step 6: Access Application
```
kubectl get svc
```

Open: **http://<PUBLIC-IP>:8000**

---

## OPTION I: HOST ON GITHUB PAGES (FREE)

### Step 1: Create GitHub Account
1. Go to: **https://github.com**
2. Click "Sign up"
3. Enter email, create password, choose username
4. Complete email verification

### Step 2: Create Pages Repository
1. Click "+" icon (top right) → "New repository"
2. Name it: **yourusername.github.io**
   (replace yourusername with your actual username)
3. Click "Create repository"

### Step 3: Enable GitHub Pages
1. Click "Settings" (top right)
2. Click "Pages" in left sidebar
3. Select branch: `main`
4. Click "Save"

Your site is live at: **https://yourusername.github.io**

### Step 4: Upload Files
1. Click "Add file" → "Upload files"
2. Upload:
   - `index.html`
   - `integration.js`
   - `frontend/` folder
3. Commit changes

Wait 1-2 minutes, then visit your GitHub Pages URL!

---

## REAL-TIME TESTING AFTER DEPLOYMENT

### Test #1: Health Check
1. Open browser
2. Go to: **http://localhost:8000/api/health**
3. You should see JSON response

### Test #2: API Documentation
1. Go to: **http://localhost:8000/docs**
2. You should see Swagger UI with all endpoints
3. Click any endpoint, then "Try it out"

### Test #3: Dashboard
1. Go to: **http://localhost:8000**
2. Click tabs: Admin, Fabric, Automation, etc.
3. You should see live data

### Test #4: Load Test (Advanced)
Windows:
```
powershell -Command "1..100 | ForEach-Object { Invoke-WebRequest -Uri http://localhost:8000/api/health }"
```

Mac/Linux:
```
for i in {1..100}; do curl http://localhost:8000/api/health; done
```

---

## WHAT IF SOMETHING GOES WRONG?

### Problem: "Port 8000 already in use"
**Solution:**
```
docker compose down
docker compose up -d --build
```

### Problem: "Docker container won't start"
**Solution:**
```
docker compose logs backend
```
Read the error, fix it, then restart.

### Problem: "Connection refused" when accessing localhost:8000
**Solution:**
```
docker compose ps
```
Check if backend is running. If not:
```
docker compose logs backend
```

### Problem: "Kubernetes pod stuck pending"
**Solution:**
```
kubectl describe pod <pod-name> -n jakal
```
Read the error and troubleshoot.

### Problem: Out of disk space
**Solution:**
```
docker system prune -a --volumes
```

---

## FINAL STEP: CELEBRATE! 🎉

You've successfully deployed JAKAL Enterprise Application!

✅ Local development ready  
✅ Container registry ready  
✅ Kubernetes cluster ready  
✅ Cloud deployment ready  
✅ GitHub Pages live  

**Your app is now accessible to the world!**

---

**Next Steps:**
1. Monitor your deployment (watch logs)
2. Share your GitHub Pages link: https://yourusername.github.io
3. Scale horizontally (add more replicas)
4. Set up monitoring and alerts
5. Configure custom domain (optional)

---

**All steps complete. JAKAL v3.0 is running in production.**
