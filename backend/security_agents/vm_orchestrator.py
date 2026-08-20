"""
JAKAL VM Orchestrator
======================
Provisions and manages *local* lab/sandbox containers on the Docker daemon
this backend is running on -- e.g. a disposable Kali/Ubuntu box to run your
own tool wrappers against, or an isolated environment to detonate a sample
in. This is infrastructure you own and control end to end.

Explicitly NOT in scope, by design:
  - Anything that connects out to or controls a machine this backend does
    not itself own (no remote-host session brokering, no C2-style agents).
  - Privileged/host-network containers. Sandboxes run unprivileged, on an
    isolated bridge network, with no host device or volume mounts beyond
    an explicit per-sandbox scratch dir.

`exec_in_sandbox` runs a command inside a container YOU provisioned here,
on YOUR docker daemon -- equivalent to `docker exec`, not a remote-access
payload. If the `docker` package or daemon isn't available, every method
degrades to a clear "docker unavailable" error rather than silently no-op.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import docker
    from docker.errors import DockerException, NotFound
    DOCKER_SDK_AVAILABLE = True
except ImportError:
    DOCKER_SDK_AVAILABLE = False
    logger.warning("docker SDK not installed. VM Orchestrator will report sandboxes as unavailable.")

# Small, well-known base images only. Deliberately not exposing an
# arbitrary-image parameter from the API layer -- keeps this from becoming
# a generic "pull and run anything" endpoint.
ALLOWED_IMAGES = {
    "ubuntu-lab": "ubuntu:22.04",
    "kali-lab": "kalilinux/kali-rolling",
    "python-lab": "python:3.11-slim",
}

_LABEL_KEY = "jakal.sandbox"


class VMOrchestrator:
    def __init__(self, db_manager=None):
        self.db = db_manager
        self._client = None
        if DOCKER_SDK_AVAILABLE:
            try:
                self._client = docker.from_env()
                self._client.ping()
            except Exception as e:
                logger.warning(f"Docker daemon not reachable: {e}")
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def list_images(self) -> Dict[str, str]:
        return dict(ALLOWED_IMAGES)

    def create_sandbox(self, name: str, image_key: str = "ubuntu-lab", operator_id: str = "system") -> Dict[str, Any]:
        if not self.available:
            return {"status": "error", "error": "docker daemon unavailable"}
        if image_key not in ALLOWED_IMAGES:
            return {"status": "error", "error": f"unknown image_key. choose from {list(ALLOWED_IMAGES)}"}

        image = ALLOWED_IMAGES[image_key]
        sandbox_id = str(uuid.uuid4())[:12]
        container_name = f"jakal-sandbox-{sandbox_id}"

        try:
            self._client.images.pull(image) if not self._image_present(image) else None
            container = self._client.containers.run(
                image,
                name=container_name,
                command="sleep infinity",
                detach=True,
                network_mode="bridge",
                privileged=False,
                mem_limit="512m",
                pids_limit=256,
                labels={_LABEL_KEY: "true", "jakal.name": name, "jakal.operator": operator_id},
            )
        except Exception as e:
            logger.error(f"Sandbox creation failed: {e}")
            return {"status": "error", "error": str(e)}

        record = {
            "sandbox_id": sandbox_id,
            "container_id": container.id,
            "container_name": container_name,
            "name": name,
            "image": image,
            "status": "running",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "operator_id": operator_id,
        }
        if self.db:
            self.db.insert_sandbox(record)
            self.db.insert_log({
                "event": "SANDBOX_CREATED", "action": "vm_orchestrator_create",
                "status": "success", "operator_id": operator_id,
                "details": {"sandbox_id": sandbox_id, "image": image},
            })
        return {"status": "created", **record}

    def list_sandboxes(self) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        containers = self._client.containers.list(all=True, filters={"label": _LABEL_KEY})
        out = []
        for c in containers:
            out.append({
                "container_id": c.id,
                "container_name": c.name,
                "name": c.labels.get("jakal.name"),
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id,
            })
        return out

    def exec_in_sandbox(self, container_name: str, command: str, operator_id: str = "system") -> Dict[str, Any]:
        """Run a command inside a sandbox this orchestrator created. This is
        `docker exec` against your own local container -- not a remote
        session against a target you don't control."""
        if not self.available:
            return {"status": "error", "error": "docker daemon unavailable"}
        try:
            container = self._client.containers.get(container_name)
            if _LABEL_KEY not in (container.labels or {}):
                return {"status": "error", "error": "refusing to exec in a non-JAKAL-managed container"}
            result = container.exec_run(command, demux=True, tty=False)
            stdout, stderr = result.output if result.output else (b"", b"")
            record = {
                "status": "completed",
                "exit_code": result.exit_code,
                "stdout": (stdout or b"").decode("utf-8", errors="replace"),
                "stderr": (stderr or b"").decode("utf-8", errors="replace"),
            }
        except NotFound:
            return {"status": "error", "error": "sandbox not found"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

        if self.db:
            self.db.insert_log({
                "event": "SANDBOX_EXEC", "action": "vm_orchestrator_exec",
                "status": record["status"], "operator_id": operator_id,
                "details": {"container_name": container_name, "command": command, "exit_code": record["exit_code"]},
            })
        return record

    def destroy_sandbox(self, container_name: str, operator_id: str = "system") -> Dict[str, Any]:
        if not self.available:
            return {"status": "error", "error": "docker daemon unavailable"}
        try:
            container = self._client.containers.get(container_name)
            if _LABEL_KEY not in (container.labels or {}):
                return {"status": "error", "error": "refusing to remove a non-JAKAL-managed container"}
            container.remove(force=True)
        except NotFound:
            return {"status": "error", "error": "sandbox not found"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

        if self.db:
            self.db.update_sandbox_status(container_name, "destroyed")
            self.db.insert_log({
                "event": "SANDBOX_DESTROYED", "action": "vm_orchestrator_destroy",
                "status": "success", "operator_id": operator_id,
                "details": {"container_name": container_name},
            })
        return {"status": "destroyed", "container_name": container_name}

    def _image_present(self, image: str) -> bool:
        try:
            self._client.images.get(image)
            return True
        except Exception:
            return False
