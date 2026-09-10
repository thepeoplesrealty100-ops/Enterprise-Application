#!/usr/bin/env python3
"""
jakal_agent.py — JAKAL endpoint agent (spoke) [roadmap #4]

A real, dependency-light agent. Registers with the JAKAL hub, heartbeats,
reports live inventory (OS, IP, installed software, users, open ports), and
executes queued commands (ping, inventory refresh, collect diagnostics).
Only stdlib + `requests` are required; `psutil` enriches ports/users if present.

Usage:
    python jakal_agent.py --server http://localhost:8000
    (identity is cached in ~/.jakal_agent.json so re-runs keep the same agent_id)

Safe by design: it does NOT execute arbitrary shell by default. `execute_script`
commands are ignored unless JAKAL_AGENT_ALLOW_EXEC=1 is set by the machine owner.
"""
import argparse
import json
import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("jakal_agent requires `requests` (pip install requests)")

STATE_FILE = os.path.join(os.path.expanduser("~"), ".jakal_agent.json")
HEARTBEAT_SECONDS = 30


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except OSError:
        return socket.gethostbyname(socket.gethostname()) if socket.gethostname() else "127.0.0.1"


def collect_software():
    """Installed Python packages as OSV-PyPI-ready inventory. (Extendable to
    OS package managers: dpkg/rpm/winget — kept to PyPI here for portability.)"""
    pkgs = []
    try:
        from importlib import metadata
        for dist in metadata.distributions():
            name = dist.metadata["Name"]; ver = dist.version
            if name and ver:
                pkgs.append({"name": name, "version": ver, "ecosystem": "PyPI"})
    except Exception:
        pass
    return pkgs


def collect_ports():
    ports = []
    try:
        import psutil
        for c in psutil.net_connections(kind="inet"):
            if c.status == "LISTEN" and c.laddr:
                ports.append(c.laddr.port)
    except Exception:
        pass
    return sorted(set(ports))


def collect_users():
    users = []
    try:
        import psutil
        users = sorted({u.name for u in psutil.users()})
    except Exception:
        try:
            users = [os.getlogin()]
        except OSError:
            pass
    return users


def system_info():
    return {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_version": platform.platform(),
        "ip": _local_ip(),
    }


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


class Agent:
    def __init__(self, server):
        self.server = server.rstrip("/")
        self.state = load_state()
        self.agent_id = self.state.get("agent_id")
        self.key = self.state.get("agent_key")

    def _url(self, p):
        return f"{self.server}{p}"

    def register(self):
        info = system_info()
        body = dict(info, agent_id=self.agent_id, tags=[info["os"].lower()])
        r = requests.post(self._url("/api/agents/register"), json=body, timeout=15)
        r.raise_for_status()
        d = r.json()
        self.agent_id = d["agent_id"]; self.key = d["agent_key"]
        save_state({"agent_id": self.agent_id, "agent_key": self.key})
        print(f"[jakal-agent] registered as {self.agent_id} ({info['hostname']} / {info['os']} / {info['ip']})")

    def _h(self):
        return {"X-Agent-Key": self.key}

    def heartbeat(self):
        r = requests.post(self._url(f"/api/agents/heartbeat?agent_id={self.agent_id}"), headers=self._h(), timeout=15)
        r.raise_for_status(); return r.json()

    def push_inventory(self):
        body = {"agent_id": self.agent_id, "software": collect_software(),
                "users": collect_users(), "ports": collect_ports(), "os_detail": system_info()}
        r = requests.post(self._url("/api/agents/inventory"), json=body, headers=self._h(), timeout=30)
        r.raise_for_status()
        print(f"[jakal-agent] inventory pushed: {r.json().get('software_count')} packages")
        return r.json()

    def poll_and_run(self):
        r = requests.get(self._url(f"/api/agents/{self.agent_id}/commands"), headers=self._h(), timeout=15)
        r.raise_for_status()
        for cmd in r.json().get("commands", []):
            self.run_command(cmd)

    def run_command(self, cmd):
        action = cmd.get("action"); cmd_id = cmd.get("cmd_id"); payload = cmd.get("payload") or {}
        print(f"[jakal-agent] command {cmd_id}: {action}")
        status, result = "completed", {}
        try:
            if action == "fleet:ping":
                result = {"pong": True, "at": datetime.now(timezone.utc).isoformat()}
            elif action in ("fleet:collect_diagnostics", "inventory_refresh"):
                self.push_inventory(); result = {"refreshed": True}
            elif action == "fleet:execute_script":
                if os.getenv("JAKAL_AGENT_ALLOW_EXEC") == "1":
                    import subprocess
                    shell = payload.get("shell", "bash"); script = payload.get("script", "")
                    exe = {"bash": ["bash", "-c"], "powershell": ["powershell", "-Command"],
                           "python": [sys.executable, "-c"]}.get(shell, ["bash", "-c"])
                    p = subprocess.run(exe + [script], capture_output=True, text=True,
                                       timeout=int(payload.get("timeout_sec", 60)))
                    result = {"return_code": p.returncode, "stdout": p.stdout[-4000:], "stderr": p.stderr[-2000:]}
                else:
                    status, result = "refused", {"reason": "remote exec disabled; set JAKAL_AGENT_ALLOW_EXEC=1 to allow"}
            else:
                status, result = "unsupported", {"reason": f"agent has no handler for {action}"}
        except Exception as e:
            status, result = "error", {"error": str(e)}
        requests.post(self._url(f"/api/agents/commands/{cmd_id}/result"),
                      json={"agent_id": self.agent_id, "status": status, "result": result},
                      headers=self._h(), timeout=15)

    def run(self):
        self.register(); self.push_inventory()
        print(f"[jakal-agent] online; heartbeat every {HEARTBEAT_SECONDS}s. Ctrl-C to stop.")
        while True:
            try:
                self.heartbeat(); self.poll_and_run()
            except requests.RequestException as e:
                print(f"[jakal-agent] hub unreachable: {e}")
            time.sleep(HEARTBEAT_SECONDS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=os.getenv("JAKAL_SERVER", "http://localhost:8000"))
    ap.add_argument("--once", action="store_true", help="register + push inventory once, then exit")
    a = ap.parse_args()
    agent = Agent(a.server)
    if a.once:
        agent.register(); agent.push_inventory()
    else:
        agent.run()
