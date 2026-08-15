# PHASE 4: ORACLE CLOUD DEPLOYMENT - COMPLETE GUIDE

## Overview
Deploy JAKAL Docker container to Oracle Cloud Always-Free Tier instance for production access.

**Estimated Time:** 1-2 hours
**Cost:** $0/month (Always-Free)
**Instance:** 4 vCPUs, 24 GB RAM, 100 GB boot volume

---

## PREREQUISITES

### Before Starting
- [x] Phase 3 Docker container working locally
- [x] Oracle Cloud account created
- [x] Always-Free instance provisioned
- [x] SSH key pair downloaded
- [x] Instance IP address noted

### Information You'll Need
```
Oracle Instance IP: 1.2.3.4 (EXAMPLE - get yours from Oracle)
Username: ubuntu
SSH Key: ~/.ssh/oracle_key.pem
```

---

## STEP 1: CONNECT TO ORACLE INSTANCE

### On Windows (PowerShell)

```powershell
# Navigate to SSH key directory
cd $env:USERPROFILE\.ssh

# Connect to instance (replace 1.2.3.4 with your IP)
ssh -i oracle_key.pem ubuntu@1.2.3.4
```

Expected prompt:
```
The authenticity of host '1.2.3.4 (1.2.3.4)' can't be established.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Type: `yes`

Expected output:
```
ubuntu@jakal-instance:~$
```

### Verify Connection

```bash
# Check Ubuntu version
cat /etc/os-release

# Check available disk space
df -h

# Check memory
free -h
```

---

## STEP 2: INSTALL DOCKER ON ORACLE

```bash
# Update system packages
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
sudo apt-get install -y docker.io docker-compose

# Add ubuntu user to docker group (so you don't need sudo)
sudo usermod -aG docker ubuntu

# Verify installation
docker --version
docker-compose --version
```

Expected output:
```
Docker version 24.x.x, build xxxxx
Docker Compose version 2.x.x
```

**Important:** Log out and log back in for docker group changes to take effect:
```bash
exit
ssh -i oracle_key.pem ubuntu@1.2.3.4
```

---

## STEP 3: CLONE JAKAL REPOSITORY

```bash
# Navigate to home directory
cd ~

# Clone repository (or use git if you set it up)
# Option A: If using GitHub
git clone https://github.com/yourusername/JAKAL.git

# Option B: If transferring via SCP
scp -i ~/.ssh/oracle_key.pem -r C:\Users\Freddy\projects\JAKAL ubuntu@1.2.3.4:~/JAKAL
```

Verify clone:
```bash
ls -la JAKAL/
cd JAKAL
ls -la backend/
```

---

## STEP 4: CONFIGURE ENVIRONMENT

```bash
# Navigate to project directory
cd ~/JAKAL

# Copy .env.example to .env
cp .env.example .env

# Edit .env (use nano or vi)
nano .env
```

Update the following:
```env
ENVIRONMENT=production
LOG_LEVEL=INFO
API_PORT=8000
API_BASE_URL=http://1.2.3.4:8000  # Replace with your IP

# Optional: Add API keys if available
GEMINI_API_KEY=your_key_here
IBM_QUANTUM_TOKEN=your_token_here
```

Save and exit (Ctrl+X, then Y, then Enter)

Verify:
```bash
cat .env
```

---

## STEP 5: BUILD DOCKER IMAGE ON ORACLE

```bash
# Navigate to project directory
cd ~/JAKAL

# Build Docker image
docker build -t jakal:2.0 .
```

This will take 3-5 minutes as it downloads and installs all dependencies.

Expected output:
```
[+] Building 240.5s (12/12) FINISHED
 => Successfully tagged jakal:2.0
```

Verify image was created:
```bash
docker images | grep jakal
```

Expected output:
```
jakal          2.0    abc123def456    2 minutes ago    450MB
```

---

## STEP 6: START CONTAINER ON ORACLE

```bash
# Navigate to project directory
cd ~/JAKAL

# Start container
docker-compose up -d
```

Expected output:
```
[+] Running 1/1
 ✔ Container jakal-backend  Started
```

Verify container is running:
```bash
docker ps
```

Expected output:
```
CONTAINER ID  IMAGE       COMMAND                  PORTS           STATUS
abc123def456  jakal:2.0   "uvicorn backend.app"   0.0.0.0:8000->8000/tcp   Up 5s (healthy)
```

---

## STEP 7: CONFIGURE FIREWALL

Oracle Cloud instances use UFW (Uncomplicated Firewall). We need to open port 8000.

```bash
# Check firewall status
sudo ufw status

# Enable firewall (if not enabled)
sudo ufw enable

# Allow SSH (critical - don't lock yourself out!)
sudo ufw allow 22/tcp

# Allow HTTP (port 80)
sudo ufw allow 80/tcp

# Allow HTTPS (port 443)
sudo ufw allow 443/tcp

# Allow API port (8000)
sudo ufw allow 8000/tcp

# Verify firewall rules
sudo ufw status
```

Expected output:
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
8000/tcp                   ALLOW       Anywhere
```

---

## STEP 8: VERIFY ENDPOINTS FROM LOCAL MACHINE

Back on your local Windows machine:

```powershell
# Replace 1.2.3.4 with your Oracle instance IP

# Health check
curl http://1.2.3.4:8000/health

# System status
curl http://1.2.3.4:8000/api/system/status

# API documentation (open in browser)
Start-Process http://1.2.3.4:8000/docs
```

Expected responses:
```json
{
  "status": "operational",
  "database": "healthy",
  "environment": "production",
  "version": "2.0.0",
  "phase": "2 (LLM + Quantum)"
}
```

---

## STEP 9: SETUP AUTOMATIC RESTART

Container should restart automatically if it crashes, but let's verify:

```bash
# Check container restart policy
docker inspect jakal-backend | grep -A 5 "RestartPolicy"

# If needed, update restart policy
docker update --restart=unless-stopped jakal-backend
```

---

## STEP 10: MONITOR LOGS

```bash
# View real-time logs
docker logs -f jakal-backend

# View last 100 lines
docker logs jakal-backend --tail 100

# Check if there are any errors
docker logs jakal-backend | grep ERROR
```

---

## TROUBLESHOOTING ORACLE DEPLOYMENT

### Issue: Cannot connect to instance (SSH timeout)
**Solution:** Security list rules might be blocking port 22
1. Go to Oracle Cloud Console
2. Find your instance
3. Go to "Network" → "Primary VNIC"
4. Click security list
5. Add Ingress Rule: Allow TCP port 22 from your IP

### Issue: Docker not found
**Solution:** Docker not installed
```bash
sudo apt-get install -y docker.io docker-compose
sudo usermod -aG docker ubuntu
exit  # Log out and back in
```

### Issue: Permission denied (cannot run docker)
**Solution:** User not in docker group
```bash
sudo usermod -aG docker ubuntu
exit  # Log out and back in
docker ps  # Should work now
```

### Issue: Container won't start
**Solution:** Check logs
```bash
docker logs jakal-backend
docker-compose up  # Run in foreground to see errors
```

### Issue: Container exits immediately
**Solution:** Check for errors
```bash
docker-compose logs
# Common issues:
# - .env file not found
# - Port already in use
# - Out of memory
```

### Issue: Cannot reach from local machine
**Solution:** Firewall blocking
```bash
# On Oracle instance, verify port is open
sudo ufw status
sudo ufw allow 8000/tcp

# On local machine, test connectivity
curl -v http://1.2.3.4:8000/health
```

---

## MANAGING ORACLE DEPLOYMENT

### Stop Container
```bash
cd ~/JAKAL
docker-compose down
```

### Restart Container
```bash
cd ~/JAKAL
docker-compose restart
```

### View Logs
```bash
docker-compose logs -f
```

### Update Application
```bash
cd ~/JAKAL
git pull  # If using GitHub
docker-compose down
docker build -t jakal:2.0 .
docker-compose up -d
```

### Connect to Container Shell
```bash
docker exec -it jakal-backend /bin/bash
```

### Check Resource Usage
```bash
# CPU and Memory
docker stats jakal-backend

# Disk usage
df -h
```

---

## DATABASE BACKUP

The database is persisted in `./data/jakal.duckdb` which is mounted as a volume.

### Manual Backup
```bash
cd ~/JAKAL
cp data/jakal.duckdb backups/jakal_$(date +%Y%m%d_%H%M%S).duckdb
```

### Automated Backup (Cron)
```bash
# Edit crontab
crontab -e

# Add line to backup daily at 2 AM
0 2 * * * cd ~/JAKAL && cp data/jakal.duckdb backups/jakal_$(date +\%Y\%m\%d_%H\%M\%S).duckdb

# List cron jobs
crontab -l
```

---

## PRODUCTION SETTINGS

### Update for Production
In `.env` on Oracle:

```env
ENVIRONMENT=production
LOG_LEVEL=WARNING
API_BASE_URL=http://your-domain.com:8000
```

### Rate Limiting
In `backend/config.py`:
```python
rate_limit_requests: int = 100  # requests per window
rate_limit_window: int = 60      # seconds
```

### Timeouts
```python
api_timeout: int = 30
scan_timeout: int = 3600
exploit_timeout: int = 600
```

---

## HTTPS SETUP (OPTIONAL)

For production, use SSL/TLS. Install nginx as reverse proxy:

```bash
# Install nginx
sudo apt-get install -y nginx

# Install certbot (Let's Encrypt)
sudo apt-get install -y certbot python3-certbot-nginx

# Get certificate (requires domain)
sudo certbot certonly --standalone -d your-domain.com

# Configure nginx (See PHASE_5_HARDENING.md)
```

---

## MONITORING

### Health Check
```powershell
# From local machine
curl http://1.2.3.4:8000/health
```

### Container Status
```bash
# On Oracle instance
docker ps
docker-compose ps
```

### Database Status
```bash
docker exec jakal-backend curl http://localhost:8000/api/system/status
```

### Logs
```bash
docker logs jakal-backend -f
```

---

## NEXT STEPS (PHASE 5)

Once container is running on Oracle:

1. ✅ Verify health check passes
2. ✅ Test all endpoints from local machine
3. ✅ Check logs are being written
4. ✅ Monitor for 24 hours
5. → Proceed to Phase 5: Production Hardening

---

## QUICK REFERENCE

### SSH Connection
```powershell
ssh -i $env:USERPROFILE\.ssh\oracle_key.pem ubuntu@1.2.3.4
```

### Start Container
```bash
cd ~/JAKAL && docker-compose up -d
```

### Check Status
```bash
docker ps
curl http://localhost:8000/health
```

### View Logs
```bash
docker logs -f jakal-backend
```

### Stop Container
```bash
cd ~/JAKAL && docker-compose down
```

---

## SUCCESS CHECKLIST

- [ ] SSH connection works
- [ ] Docker installed on Oracle
- [ ] JAKAL repository cloned
- [ ] .env configured
- [ ] Docker image built
- [ ] Container running (docker ps shows healthy)
- [ ] Firewall allows port 8000
- [ ] Health check returns 200 from local machine
- [ ] API docs accessible at http://instance-ip:8000/docs
- [ ] Database accessible
- [ ] Logs are being written

---

**Phase 4 Status: PRODUCTION DEPLOYMENT COMPLETE**
**Next: Phase 5 - Production Hardening**
