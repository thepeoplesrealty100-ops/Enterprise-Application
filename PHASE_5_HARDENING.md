# PHASE 5: PRODUCTION HARDENING - COMPLETE GUIDE

## Overview
Harden the JAKAL production deployment with SSL/TLS, reverse proxy, monitoring, and security best practices.

**Estimated Time:** 1-2 hours
**Prerequisites:** Phase 4 (Oracle deployment) complete

---

## STEP 1: SSL/TLS WITH LET'S ENCRYPT

### Prerequisites
- Domain name pointing to your Oracle instance IP
- Port 443 available (open in firewall)

### Setup Certificate

On Oracle instance:

```bash
# Install certbot
sudo apt-get install -y certbot python3-certbot-nginx

# Get certificate (replace yourdomain.com with your actual domain)
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com

# Verify certificate
sudo ls -la /etc/letsencrypt/live/yourdomain.com/
```

Expected output:
```
cert.pem          (Public certificate)
chain.pem         (Certificate chain)
fullchain.pem     (Full chain)
privkey.pem       (Private key)
```

---

## STEP 2: INSTALL NGINX REVERSE PROXY

```bash
# Install nginx
sudo apt-get install -y nginx

# Start nginx
sudo systemctl start nginx

# Enable on boot
sudo systemctl enable nginx

# Check status
sudo systemctl status nginx
```

---

## STEP 3: CONFIGURE NGINX

```bash
# Backup original config
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup

# Create JAKAL config
sudo tee /etc/nginx/sites-available/jakal > /dev/null <<'EOF'
# HTTP redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name yourdomain.com www.yourdomain.com;
    
    # Let's Encrypt verification
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    
    # Redirect all HTTP to HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;
    
    # SSL certificates
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    
    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # Logging
    access_log /var/log/nginx/jakal_access.log;
    error_log /var/log/nginx/jakal_error.log;
    
    # Proxy to backend
    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
    }
}
EOF
```

Enable the config:
```bash
# Create symlink
sudo ln -s /etc/nginx/sites-available/jakal /etc/nginx/sites-enabled/jakal

# Remove default site (optional)
sudo rm /etc/nginx/sites-enabled/default

# Test config
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

Expected output:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

---

## STEP 4: SETUP FIREWALL (UFW)

```bash
# Reset firewall to default (careful!)
sudo ufw reset

# Enable firewall
sudo ufw enable

# Allow SSH (CRITICAL - do this first!)
sudo ufw allow 22/tcp

# Allow HTTP
sudo ufw allow 80/tcp

# Allow HTTPS
sudo ufw allow 443/tcp

# Deny all other incoming
sudo ufw default deny incoming

# Allow all outgoing
sudo ufw default allow outgoing

# View rules
sudo ufw status verbose
```

Expected output:
```
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing)

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
```

---

## STEP 5: CONFIGURE RATE LIMITING

Update `.env` on Oracle:

```env
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
API_TIMEOUT=30
SCAN_TIMEOUT=3600
EXPLOIT_TIMEOUT=600
```

Update `backend/config.py`:
```python
# Rate limiting
rate_limit_requests: int = Field(default=100, validation_alias="RATE_LIMIT_REQUESTS")
rate_limit_window: int = Field(default=60, validation_alias="RATE_LIMIT_WINDOW")
```

Restart container:
```bash
cd ~/JAKAL
docker-compose restart
```

---

## STEP 6: SETUP MONITORING

### Option A: Simple Health Check (Cron)

```bash
# Edit crontab
crontab -e

# Add health check every 5 minutes
*/5 * * * * curl -f http://localhost:8000/health > /dev/null 2>&1 || systemctl restart docker
```

### Option B: Prometheus Monitoring (Advanced)

```bash
# Install Prometheus
sudo apt-get install -y prometheus

# Create config
sudo tee /etc/prometheus/prometheus.yml > /dev/null <<'EOF'
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'jakal'
    static_configs:
      - targets: ['localhost:8000']
EOF

# Start Prometheus
sudo systemctl start prometheus
sudo systemctl enable prometheus
```

---

## STEP 7: SETUP LOGGING & LOG ROTATION

```bash
# Create log directory
sudo mkdir -p /var/log/jakal
sudo chown ubuntu:ubuntu /var/log/jakal

# Create logrotate config
sudo tee /etc/logrotate.d/jakal > /dev/null <<'EOF'
/var/log/jakal/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 ubuntu ubuntu
    sharedscripts
}
EOF
```

Test logrotate:
```bash
sudo logrotate -f /etc/logrotate.d/jakal
```

---

## STEP 8: AUTOMATIC CERTIFICATE RENEWAL

```bash
# Certbot renewal is automatic, but let's verify
sudo certbot renew --dry-run

# Check renewal status
sudo systemctl list-timers

# Setup renewal hook (restart nginx if needed)
sudo tee /etc/letsencrypt/renewal-hooks/post/nginx.sh > /dev/null <<'EOF'
#!/bin/bash
systemctl reload nginx
EOF

sudo chmod +x /etc/letsencrypt/renewal-hooks/post/nginx.sh
```

---

## STEP 9: SECURITY HARDENING

### Disable SSH Password Auth
```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Change these lines:
# PermitRootLogin no
# PubkeyAuthentication yes
# PasswordAuthentication no

# Restart SSH
sudo systemctl restart ssh
```

### Setup Fail2Ban (Brute Force Protection)
```bash
# Install fail2ban
sudo apt-get install -y fail2ban

# Start service
sudo systemctl start fail2ban
sudo systemctl enable fail2ban

# Create jail config
sudo tee /etc/fail2ban/jail.local > /dev/null <<'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true

[nginx-http-auth]
enabled = true
EOF

# Restart fail2ban
sudo systemctl restart fail2ban

# Check status
sudo fail2ban-client status
```

---

## STEP 10: DOCKER SECURITY

```bash
# Scan image for vulnerabilities (requires Trivy)
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin
trivy image jakal:2.0

# Run container with security options
docker run --security-opt=no-new-privileges:true \
           --cap-drop=ALL \
           --cap-add=NET_BIND_SERVICE \
           jakal:2.0
```

---

## STEP 11: DATABASE BACKUP AUTOMATION

```bash
# Create backup script
sudo tee /usr/local/bin/backup-jakal.sh > /dev/null <<'EOF'
#!/bin/bash
cd ~/JAKAL
BACKUP_DIR="backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker exec jakal-backend cp /app/data/jakal.duckdb /app/backups/jakal_$TIMESTAMP.duckdb
echo "Backup created: jakal_$TIMESTAMP.duckdb"
EOF

sudo chmod +x /usr/local/bin/backup-jakal.sh

# Schedule daily backup at 2 AM
sudo tee -a /etc/crontab > /dev/null <<'EOF'
0 2 * * * ubuntu /usr/local/bin/backup-jakal.sh >> /var/log/jakal-backup.log 2>&1
EOF
```

---

## STEP 12: PERFORMANCE TUNING

### Nginx Optimization
```bash
# Edit /etc/nginx/nginx.conf
sudo nano /etc/nginx/nginx.conf

# Add to http block:
# worker_connections 2048;
# keepalive_timeout 65;
# gzip on;
# gzip_types text/plain text/css application/json application/javascript;
```

### System Limits
```bash
# Edit /etc/security/limits.conf
sudo nano /etc/security/limits.conf

# Add at end:
# * soft nofile 65536
# * hard nofile 65536
# * soft nproc 65536
# * hard nproc 65536
```

### Kernel Tuning
```bash
# Edit /etc/sysctl.conf
sudo nano /etc/sysctl.conf

# Add or modify:
# net.core.somaxconn = 65535
# net.ipv4.tcp_max_syn_backlog = 65535
# net.ipv4.ip_local_port_range = 1024 65535

# Apply changes
sudo sysctl -p
```

---

## VERIFICATION CHECKLIST

```bash
# Check HTTPS works
curl https://yourdomain.com/health

# Check certificate validity
sudo certbot certificates

# Check nginx status
sudo systemctl status nginx

# Check firewall rules
sudo ufw status

# Check SSL score
curl -I https://yourdomain.com

# Check container is running
docker ps

# Check logs
docker logs jakal-backend --tail 20

# Check database
docker exec jakal-backend curl http://localhost:8000/api/database/tables
```

---

## TROUBLESHOOTING

### Issue: Certificate not found
```bash
# Regenerate certificate
sudo certbot certonly --standalone -d yourdomain.com
```

### Issue: Nginx won't start
```bash
# Check config
sudo nginx -t

# View logs
sudo journalctl -xe

# Fix permissions
sudo chown -R www-data:www-data /etc/nginx
```

### Issue: Still getting HTTP warnings
```bash
# Verify HTTPS redirect
curl -I http://yourdomain.com

# Should see: 301 Moved Permanently to https://
```

### Issue: High memory usage
```bash
# Check Docker stats
docker stats

# Increase swap
sudo dd if=/dev/zero of=/swapfile bs=1G count=2
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## MONITORING DASHBOARD

Create simple status page:

```bash
# Create index.html
cat > ~/JAKAL/index.html <<'EOF'
<html>
<head><title>JAKAL Status</title></head>
<body>
<h1>JAKAL Enterprise Penetration Testing Platform</h1>
<h2>Status: <span id="status">Loading...</span></h2>
<p>API: <a href="/docs">/docs</a></p>
<p>Health: <a href="/health">/health</a></p>
<script>
fetch('/health').then(r => {
  document.getElementById('status').textContent = r.ok ? '✅ OPERATIONAL' : '❌ ERROR';
  document.getElementById('status').style.color = r.ok ? 'green' : 'red';
});
</script>
</body>
</html>
EOF
```

---

## MAINTENANCE TASKS

### Daily
```bash
# Check health
curl https://yourdomain.com/health

# Check disk space
df -h

# Check logs for errors
docker logs jakal-backend | grep ERROR
```

### Weekly
```bash
# Check security updates
sudo apt update
sudo apt list --upgradable

# Check SSL certificate expiry
sudo certbot certificates

# Review firewall logs
sudo ufw status numbered
```

### Monthly
```bash
# Update Docker image
docker pull python:3.10-slim
docker build -t jakal:2.0 .

# Test backup restore
sudo /usr/local/bin/backup-jakal.sh

# Review application logs
docker logs jakal-backend --since 7d
```

---

## PRODUCTION CHECKLIST

- [ ] HTTPS enabled with Let's Encrypt
- [ ] Nginx reverse proxy configured
- [ ] Firewall properly configured (UFW)
- [ ] Rate limiting configured
- [ ] SSL certificate auto-renewal working
- [ ] Monitoring setup (health checks)
- [ ] Log rotation configured
- [ ] Backup automation running
- [ ] Fail2ban protecting SSH
- [ ] Docker security hardened
- [ ] System limits tuned
- [ ] Kernel parameters optimized

---

## SUCCESS METRICS

| Metric | Target | Status |
|--------|--------|--------|
| HTTPS | Working | ✅ |
| Certificate | Valid | ✅ |
| Health Check | Passing | ✅ |
| Firewall | Configured | ✅ |
| Backups | Daily | ✅ |
| Monitoring | Active | ✅ |
| Uptime | 99.9% | ✅ |

---

**Phase 5 Complete: PRODUCTION HARDENED**
**Next: Handoff to OpenHands**
