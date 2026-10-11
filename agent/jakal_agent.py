#!/usr/bin/env python3
"""
agent/jakal_agent.py — the real JAKAL endpoint agent.

backend/routers/remote_exec.py and backend/routers/fleet_agent.py have
always documented this agent's existence and protocol in their own
docstrings ("Agents (agent/jakal_agent.py) run a queued
fleet:execute_script command...") -- both hub-side routers were fully
real and complete, but the spoke-side client they were built for was
never actually written, so `agent_endpoints` could only ever be empty
and Live Execution had nothing to point at. This is that client.

Protocol (all endpoints are backend/routers/fleet_agent.py and
backend/routers/remote_exec.py, already live):
  1. POST /api/agents/register        {hostname, os, os_version, ip, tags}
                                       -> {agent_id, agent_key}
  2. loop, every --heartbeat-interval seconds:
     POST /api/agents/heartbeat?agent_id=...   (X-Agent-Key header)
     GET  /api/agents/{agent_id}/commands       (X-Agent-Key header)
       for each pending command with action == "fleet:execute_script":
         run payload["script"] with payload["shell"] in a subprocess,
         stream stdout/stderr chunks to POST /api/exec/chunk as they
         arrive (the same shape routers/remote_exec.py's WebSocket hub
         fans out to any live viewer), then
         POST /api/agents/commands/{cmd_id}/result

Scope, deliberately: this executes whatever script the operator staged
through their own JAKAL dashboard on their own registered machine --
the same trust boundary as routers/scripts.py's sandbox execution
("execute directly -- dangerous, for demo only!", its own words) and
routers/integrations.py's open-by-design localhost single-operator
model. It is not a hardened, sandboxed RMM agent (no container
isolation, no privilege dropping) -- it is the reference implementation
this protocol was designed for, matching this repo's existing honesty
about what "sandbox execution" here actually means. Do not point this
at a machine you do not own or a network you do not control.

Usage:
  python agent/jakal_agent.py --server http://localhost:8000
  python agent/jakal_agent.py --server http://localhost:8000 --hostname my-box --tags dev,demo

State (agent_id + agent_key, so re-running reuses the same identity
instead of registering a new agent every restart) persists to
--state-file (default: agent/.jakal_agent_state.json, gitignored).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    print("This agent needs the 'requests' package: pip install requests", file=sys.stderr)
    sys.exit(1)


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _os_name() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return "linux"


class JakalAgent:
    def __init__(self, server: str, hostname: str, tags: List[str], state_file: Path,
                 heartbeat_interval: int, poll_interval: int, exec_timeout: int):
        self.server = server.rstrip("/")
        self.hostname = hostname
        self.tags = tags
        self.state_file = state_file
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self.exec_timeout = exec_timeout
        self.agent_id: Optional[str] = None
        self.agent_key: Optional[str] = None
        self.session = requests.Session()

    def _load_state(self) -> Optional[Dict[str, str]]:
        if self.state_file.is_file():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return None

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps({"agent_id": self.agent_id, "agent_key": self.agent_key}), encoding="utf-8"
        )

    def register(self) -> None:
        state = self._load_state()
        payload = {
            "agent_id": state.get("agent_id") if state else None,
            "hostname": self.hostname,
            "os": _os_name(),
            "os_version": platform.platform(),
            "ip": _local_ip(),
            "tags": self.tags,
        }
        resp = self.session.post(f"{self.server}/api/agents/register", json=payload, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        self.agent_id = body["agent_id"]
        self.agent_key = body["agent_key"]
        self._save_state()
        print(f"[jakal-agent] registered as {self.agent_id} ({self.hostname}) against {self.server}")

    def _headers(self) -> Dict[str, str]:
        return {"X-Agent-Key": self.agent_key or ""}

    def heartbeat(self) -> int:
        resp = self.session.post(
            f"{self.server}/api/agents/heartbeat",
            params={"agent_id": self.agent_id},
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("pending_commands", 0)

    def poll_commands(self) -> List[Dict[str, Any]]:
        resp = self.session.get(
            f"{self.server}/api/agents/{self.agent_id}/commands",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("commands", [])

    def _shell_argv(self, shell: str, script: str) -> List[str]:
        if shell == "powershell":
            return ["powershell", "-NoProfile", "-Command", script]
        if shell == "python":
            return [sys.executable, "-c", script]
        return ["bash", "-c", script]  # default: bash

    def _send_chunk(self, execution_id: str, stream_type: str, text: str, done: bool) -> None:
        try:
            self.session.post(
                f"{self.server}/api/exec/chunk",
                json={
                    "executionId": execution_id, "endpointId": self.agent_id,
                    "osType": _os_name(), "streamType": stream_type,
                    "outputChunk": text, "done": done,
                },
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"[jakal-agent] chunk delivery failed: {e}", file=sys.stderr)

    def _run_execute_script(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        payload = cmd.get("payload") or {}
        shell = payload.get("shell", "bash")
        script = payload.get("script", "")
        execution_id = payload.get("execution_id", f"exec_{uuid.uuid4().hex[:8]}")
        argv = self._shell_argv(shell, script)
        print(f"[jakal-agent] executing {execution_id} ({shell}, {len(script)} bytes)")
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.exec_timeout,
            )
            if proc.stdout:
                self._send_chunk(execution_id, "stdout", proc.stdout[:20000], False)
            if proc.stderr:
                stream = "powershell_error" if shell == "powershell" else "stderr"
                self._send_chunk(execution_id, stream, proc.stderr[:20000], False)
            self._send_chunk(execution_id, "stdout", "", True)
            return {"exit_code": proc.returncode, "execution_id": execution_id}
        except subprocess.TimeoutExpired:
            self._send_chunk(execution_id, "stderr", f"[timed out after {self.exec_timeout}s]", True)
            return {"exit_code": None, "execution_id": execution_id, "error": "timeout"}
        except Exception as e:  # noqa: BLE001
            self._send_chunk(execution_id, "stderr", f"[agent error: {e}]", True)
            return {"exit_code": None, "execution_id": execution_id, "error": str(e)}

    def _post_result(self, cmd_id: str, result: Dict[str, Any], status: str) -> None:
        try:
            self.session.post(
                f"{self.server}/api/agents/commands/{cmd_id}/result",
                json={"agent_id": self.agent_id, "result": result, "status": status},
                headers=self._headers(), timeout=15,
            )
        except requests.RequestException as e:
            print(f"[jakal-agent] result post failed: {e}", file=sys.stderr)

    def handle_command(self, cmd: Dict[str, Any]) -> None:
        action = cmd.get("action")
        if action == "fleet:execute_script":
            result = self._run_execute_script(cmd)
            status = "completed" if result.get("exit_code") == 0 else "failed" if "error" in result else "completed"
            self._post_result(cmd["cmd_id"], result, status)
        else:
            print(f"[jakal-agent] unsupported action '{action}', skipping")
            self._post_result(cmd["cmd_id"], {"error": f"unsupported action: {action}"}, "failed")

    def run_forever(self) -> None:
        self.register()
        print(f"[jakal-agent] heartbeat every {self.heartbeat_interval}s, "
              f"polling commands every {self.poll_interval}s. Ctrl+C to stop.")
        last_heartbeat = 0.0
        while True:
            now = time.time()
            if now - last_heartbeat >= self.heartbeat_interval:
                try:
                    self.heartbeat()
                except requests.RequestException as e:
                    print(f"[jakal-agent] heartbeat failed: {e}", file=sys.stderr)
                last_heartbeat = now
            try:
                for cmd in self.poll_commands():
                    self.handle_command(cmd)
            except requests.RequestException as e:
                print(f"[jakal-agent] poll failed: {e}", file=sys.stderr)
            time.sleep(self.poll_interval)


def main() -> None:
    p = argparse.ArgumentParser(description="JAKAL endpoint agent (hub-and-spoke RMM client)")
    p.add_argument("--server", default=os.getenv("JAKAL_SERVER", "http://localhost:8000"))
    p.add_argument("--hostname", default=socket.gethostname())
    p.add_argument("--tags", default="", help="comma-separated, e.g. dev,demo")
    p.add_argument("--state-file", default=str(Path(__file__).parent / ".jakal_agent_state.json"))
    p.add_argument("--heartbeat-interval", type=int, default=30)
    p.add_argument("--poll-interval", type=int, default=3)
    p.add_argument("--exec-timeout", type=int, default=120)
    args = p.parse_args()

    agent = JakalAgent(
        server=args.server, hostname=args.hostname,
        tags=[t.strip() for t in args.tags.split(",") if t.strip()],
        state_file=Path(args.state_file),
        heartbeat_interval=args.heartbeat_interval,
        poll_interval=args.poll_interval,
        exec_timeout=args.exec_timeout,
    )
    try:
        agent.run_forever()
    except KeyboardInterrupt:
        print("\n[jakal-agent] stopped.")


if __name__ == "__main__":
    main()
