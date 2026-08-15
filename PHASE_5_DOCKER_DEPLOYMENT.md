# Phase 5: Docker & Deployment Files

Create these files in your project root:

---

## File 1: Dockerfile (backend/Dockerfile)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for security tools
RUN apt-get update && apt-get install -y \
    nmap nikto sqlmap gobuster dnsmasq \
    curl wget git vim nano \
    openssh-client postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY GACyber_Tool_Kit/ ./GACyber_Tool_Kit/

# Create data directory
RUN mkdir -p data logs backups

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## File 2: docker-compose.yml

```yaml
version: '3.9'

services:
  jakal-backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    container_name: jakal-backend
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=production
      - LOG_LEVEL=INFO
      - API_PORT=8000
      - DATABASE_URL=data/jakal.duckdb
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - IBM_QUANTUM_TOKEN=${IBM_QUANTUM_TOKEN}
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
      - FIREBASE_API_KEY=${FIREBASE_API_KEY}
      - ALLOWED_ORIGINS=http://localhost:3000,https://jakal.vercel.app
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./backups:/app/backups
      - ./GACyber_Tool_Kit:/app/GACyber_Tool_Kit:ro
    networks:
      - jakal_network
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  # Optional: Local database UI (pgAdmin for Supabase)
  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: jakal-pgadmin
    environment:
      - PGADMIN_DEFAULT_EMAIL=admin@jakal.local
      - PGADMIN_DEFAULT_PASSWORD=admin
    ports:
      - "5050:80"
    networks:
      - jakal_network
    restart: unless-stopped

networks:
  jakal_network:
    driver: bridge

volumes:
  data:
  logs:
  backups:
```

---

## File 3: .dockerignore

```
__pycache__
*.pyc
*.pyo
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
.coverage
htmlcov
.DS_Store
Thumbs.db
*.log
.venv
venv
```

---

## Deployment to Oracle Cloud

### Step 1: SSH into Oracle Instance

```bash
ssh -i oracle_key.pem ubuntu@YOUR_ORACLE_IP
```

### Step 2: Clone Repository

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/JAKAL.git
cd JAKAL
```

### Step 3: Install Docker

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker
```

### Step 4: Setup Environment

```bash
# Copy credentials
cp .env.example .env
nano .env  # Fill in all values

# Create data directories
mkdir -p data logs backups
```

### Step 5: Build & Run

```bash
# Build image
docker build -t jakal-backend:latest -f backend/Dockerfile .

# Run with docker-compose
docker-compose up -d

# Verify
docker ps
curl http://localhost:8000/health
```

### Step 6: Setup Firewall

```bash
# Allow ports 80, 443, 22, 8000
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw allow 8000
sudo ufw enable
```

### Step 7: Setup SSL with Let's Encrypt (Optional)

```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot certonly --standalone -d jakal.your-domain.com
```

### Step 8: Monitor Logs

```bash
# View logs
docker logs -f jakal-backend

# System logs
docker stats
```

---

## Testing Deployment

```bash
# Health check
curl http://YOUR_ORACLE_IP:8000/health

# Full status
curl http://YOUR_ORACLE_IP:8000/api/system/status

# LLM health
curl http://YOUR_ORACLE_IP:8000/api/llm/health

# Quantum health  
curl http://YOUR_ORACLE_IP:8000/api/quantum/health

# API docs
# Open in browser: http://YOUR_ORACLE_IP:8000/docs
```

---

## Scaling & Production

### Add Nginx Reverse Proxy

Create `nginx.conf`:

```nginx
upstream jakal_backend {
    server jakal-backend:8000;
}

server {
    listen 80;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://jakal_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://jakal_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Add to docker-compose.yml:

```yaml
  nginx:
    image: nginx:latest
    container_name: jakal-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - jakal-backend
    networks:
      - jakal_network
    restart: unless-stopped
```

---

## Backup Strategy

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/app/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Backup database
cp /app/data/jakal.duckdb $BACKUP_DIR/jakal_$DATE.duckdb

# Backup logs
tar -czf $BACKUP_DIR/logs_$DATE.tar.gz /app/logs/

# Keep only last 7 days
find $BACKUP_DIR -type f -mtime +7 -delete

echo "Backup complete: $DATE"
```

Schedule with cron:

```bash
crontab -e
# Add: 0 2 * * * /app/backup.sh
```

---

## Monitoring

### Check Container Health

```bash
docker ps
docker stats jakal-backend
docker logs jakal-backend
```

### Monitor Disk Space

```bash
df -h
du -sh /app/data
du -sh /app/logs
```

### Monitor API

```bash
# Check health
while true; do
  curl -s http://localhost:8000/health | jq .
  sleep 10
done
```

