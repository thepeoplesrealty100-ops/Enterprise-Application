# Running JAKAL on Ubuntu

Step-by-step, from a clean Ubuntu machine to a working dashboard.

Every command here was checked against the actual `Dockerfile`, `backend/app.py`
and `backend/requirements.txt` in this repo — not carried over from older notes.
For Windows/PowerShell see [RUN_LOCALLY.md](RUN_LOCALLY.md); for Kubernetes and
production concerns see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md).

**Two paths.** Path A (Docker) is the one this repo's own tooling exercises and
is what you want unless you're editing backend code. Path B (native Python) gives
you auto-reload for development.

---

## Path A — Docker (recommended)

### 1. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Let your user run Docker without `sudo`:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Get the code

```bash
git clone https://github.com/thepeoplesrealty100-ops/Enterprise-Application.git ~/Enterprise-Application
cd ~/Enterprise-Application
```

### 3. Set your master key

`JAKAL_MASTER_KEY` wraps the encryption keys stored in the database. **If you don't
set it, it's ephemeral** — anything encrypted becomes unrecoverable on restart. It
isn't a credential you obtain from anywhere; generate one now, once, and keep it.

```bash
mkdir -p data logs backups
printf 'JAKAL_MASTER_KEY=%s\n' "$(openssl rand -hex 32)" >> .env
```

Docker Compose reads a root `.env` automatically. Nothing else is required — the
LLM is optional and the app runs fine without one.

### 4. Start it

```bash
docker compose up -d --build
```

First build takes a few minutes (it compiles crypto and Qiskit wheels). Then:

```bash
curl http://localhost:8000/health
```

You should see `{"status":"operational",...}`. Open **http://localhost:8000** for
the dashboard, or **http://localhost:8000/docs** for the API reference.

### 5. Load demo data (optional but recommended)

An empty install has empty dashboards. This seeds a realistic sample engagement —
scope, discovered hosts, findings, MITRE mappings, a pending approval request:

```bash
docker compose exec jakal-backend python seed_demo_data.py
```

### Managing it

```bash
docker compose logs -f          # follow logs
docker compose restart          # restart
docker compose down             # stop (data in ./data survives)
docker compose up -d --build    # rebuild after pulling changes
```

---

## Path B — Native Python (for development)

Use this when you're editing backend code and want `--reload`.

### 1. System dependencies

Python **3.11** specifically — `requirements.txt` pins Qiskit 1.0.2 and DuckDB
0.10.0, which don't have wheels for every newer Python. On Ubuntu 24.04+, 3.11
isn't the default, so add the deadsnakes PPA:

```bash
sudo apt-get update
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev \
                        build-essential libssl-dev libffi-dev git curl nmap
```

(On Ubuntu 22.04, `python3.11` is available without the PPA — you can skip the
`add-apt-repository` line.)

`nmap` is what the recon agent actually shells out to. Without it, scanning
degrades rather than crashing, but you want it.

### 2. Get the code and create a virtualenv

```bash
git clone https://github.com/thepeoplesrealty100-ops/Enterprise-Application.git ~/Enterprise-Application
cd ~/Enterprise-Application
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r backend/requirements.txt
```

This pulls Qiskit, the PQC library and the crypto stack, so expect a few minutes.

### 3. Configure

```bash
mkdir -p data logs backups
cp backend/.env.example backend/.env
sed -i "s|^JAKAL_MASTER_KEY=.*|JAKAL_MASTER_KEY=$(openssl rand -hex 32)|" backend/.env
sed -i "s|^DUCKDB_PATH=.*|DUCKDB_PATH=../data/jakal.duckdb|" backend/.env
```

The `DUCKDB_PATH` change puts the database in `data/` alongside the Docker path,
instead of dropping `jakal.duckdb` loose inside `backend/`.

### 4. Run it

**The working directory matters.** The backend's imports are flat (`from database
import ...`), so it must start from inside `backend/`:

```bash
cd backend
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

> Running `uvicorn backend.app:app` from the repo root **will not work** — the flat
> imports fail. This matches the Dockerfile, which sets `WORKDIR /app/backend` and
> runs `uvicorn app:app`.

You don't need to set `FRONTEND_DIR`: it defaults to the repo root, where
`index.html` lives, so the dashboard is served at `/` automatically.

### 5. Seed demo data (optional)

In a second terminal:

```bash
cd ~/Enterprise-Application/backend
source ../venv/bin/activate
python seed_demo_data.py
```

---

## Verify it's actually working

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/health/detailed     # DB status, resources, features
curl http://localhost:8000/api/fleet/devices       # real discovered-host inventory
```

Then open **http://localhost:8000** and check:

1. The badge top-left reads **ONLINE**, not OFFLINE.
2. **Global Dashboard** shows fleet posture and recent agent activity.
3. Open the browser console (F12) — there should be **no CSP violations**. If the
   page renders unstyled or navigation is dead, that's the CSP allowlist; see the
   troubleshooting note in [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md).

## Run the tests

```bash
# Docker
docker compose exec jakal-backend python -m pytest tests/ -q

# Native
cd ~/Enterprise-Application/backend && source ../venv/bin/activate
python -m pytest tests/ -q
```

Expect roughly **238 passed, 41 skipped**. The skips need optional services (real
IBM Quantum hardware, a live Docker socket) — skipped by design, not broken.

---

## Troubleshooting

**`Could not set lock on file ... Conflicting lock is held`** — DuckDB allows a
single writer process. You have the server running and something else (a script, a
second server, a test run) trying to open the same database file. Stop one, or
point the second at a different `DUCKDB_PATH`.

**Port 8000 already in use** — `sudo lsof -i :8000` to find it. For Docker, change
the host side of the mapping in `docker-compose.yml` (`"8001:8000"`).

**`pip install` fails building a wheel** — you're almost certainly missing
`build-essential libssl-dev libffi-dev`, or you're not on Python 3.11. Check with
`python --version` inside the activated venv.

**Dashboard loads but every panel is empty** — nothing has been scanned yet. Run
`seed_demo_data.py` (step 5), or start a real pentest from the UI.

**`JAKAL_MASTER_KEY not set` in the logs** — expected if you skipped it. Fine for a
quick look; set it before anything you intend to keep, or encrypted data won't
survive a restart.

**Docker permission denied on the socket** — you skipped `usermod -aG docker $USER`,
or haven't started a new login session since. `newgrp docker` fixes the current shell.
