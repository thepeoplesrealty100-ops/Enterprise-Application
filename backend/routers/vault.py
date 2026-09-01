"""
backend/routers/vault.py
=========================
EAS R&D + Trade Secrets — JAKAL v2.6.

Backs two "Global Settings & Security" sub-tabs that were previously pure
frontend fiction (setTimeout()-simulated "AI scanning" and a hardcoded
"Digital Doppelganger" modal — see index.html's renderEasRdTab /
renderTradeSecretsTab before this change):

  EAS R&D ("Enhanced Application Security Research & Development"):
    A REAL dependency-vulnerability scanner. It parses this repo's
    requirements.txt files and batch-queries OSV.dev (osv.dev/docs/#tag/api,
    the Open Source Vulnerability database backed by Google, used by GitHub
    Dependabot and pip-audit itself) — no API key required, genuinely
    reachable data, not a simulation.

  Trade Secrets vault:
    A REAL encrypted-document vault for IP/trade-secret material. Every
    item is AES-256-GCM-encrypted at rest via the existing
    crypto/encryption_manager.py (the same module backing /api/crypto/*)
    before it ever reaches DuckDB, integrity-checked with a SHA3-256 hash
    of the plaintext, and access-controlled by RBAC role
    (backend/routers/iam.py) rather than "everyone who can reach the API".

Endpoints:
  POST /vault/eas-rd/scan            — run a live OSV.dev dependency scan
  GET  /vault/eas-rd/last-scan       — most recent cached scan result
  POST /vault/items                  — create an encrypted vault item
  GET  /vault/items                  — list item metadata (never plaintext)
  GET  /vault/items/{item_id}        — decrypt + return one item (RBAC-gated)
  DELETE /vault/items/{item_id}      — archive (soft delete)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

try:
    from database import get_db_manager
    from crypto.encryption_manager import EncryptionManager
    _db = get_db_manager()
    _enc = EncryptionManager(db=_db)
    VAULT_OK = True
    _VAULT_ERR = None
except Exception as _e:  # noqa: BLE001
    VAULT_OK = False
    _VAULT_ERR = str(_e)
    _db = None
    _enc = None

from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vault", tags=["vault"])

_OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
_REQUIREMENTS_FILES = [
    Path(__file__).resolve().parent.parent / "requirements.txt",
    Path(__file__).resolve().parent.parent.parent / "backend-v3" / "requirements.txt",
]
_last_scan: Optional[Dict[str, Any]] = None  # process-memory cache; good enough for a single-instance app


def _require():
    if not VAULT_OK:
        raise HTTPException(status_code=503, detail=f"Vault module unavailable: {_VAULT_ERR}")


def _audit(request: Request, user: Optional[dict], action: str, outcome: str, resource_id: str = "",
           detail: Optional[dict] = None):
    try:
        _db.insert_audit_entry({
            "actor_user_id": user["user_id"] if user else None,
            "actor_label": user["username"] if user else "anonymous",
            "action": action, "resource_type": "vault", "resource_id": resource_id,
            "outcome": outcome, "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("audit write failed for %s", action)


def _parse_requirements(path: Path) -> List[Dict[str, str]]:
    """Parses `name==version` pins; skips comments, extras, and non-pinned lines."""
    packages: List[Dict[str, str]] = []
    if not path.is_file():
        return packages
    pin_re = re.compile(r"^([A-Za-z0-9_.\-]+)\s*==\s*([A-Za-z0-9_.\-]+)")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = pin_re.match(line)
        if m:
            packages.append({"name": m.group(1), "version": m.group(2)})
    return packages


# ══════════════════════════════════════════════════════════════════════════
# EAS R&D — dependency vulnerability scan
# ══════════════════════════════════════════════════════════════════════════

@router.post("/eas-rd/scan")
async def run_eas_rd_scan(request: Request, user: dict = Depends(get_authenticated_user)):
    """
    Replaces the old fake `runEasRdUpdate()` setTimeout() theater with a real
    scan: every pinned package across backend/requirements.txt and
    backend-v3/requirements.txt is batch-queried against OSV.dev for known
    CVEs/GHSAs. Findings are the real "critical updates" the UI can act on.
    """
    global _last_scan
    _require()

    packages: List[Dict[str, str]] = []
    for path in _REQUIREMENTS_FILES:
        packages.extend(_parse_requirements(path))

    if not packages:
        result = {"scanned_at": datetime.now(timezone.utc).isoformat(), "packages_scanned": 0,
                   "findings": [], "error": "No pinned (name==version) requirements found to scan."}
        _last_scan = result
        return result

    queries = [{"package": {"name": p["name"], "ecosystem": "PyPI"}, "version": p["version"]} for p in packages]
    findings: List[Dict[str, Any]] = []
    error = None
    try:
        resp = requests.post(_OSV_BATCH_URL, json={"queries": queries}, timeout=15)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        for pkg, res in zip(packages, results):
            for vuln in res.get("vulns", []) or []:
                findings.append({
                    "package": pkg["name"], "version": pkg["version"],
                    "id": vuln.get("id"),
                    "summary": vuln.get("summary") or "(no summary provided by OSV)",
                    "aliases": vuln.get("aliases", []),
                    "modified": vuln.get("modified"),
                })
    except requests.RequestException as e:
        error = f"OSV.dev query failed ({e.__class__.__name__}); is outbound network access available? {e}"
        logger.warning("EAS R&D scan network error: %s", e)

    result = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "packages_scanned": len(packages),
        "vulnerable_packages": len({f["package"] for f in findings}),
        "findings": findings,
        "source": "https://osv.dev (Open Source Vulnerability database)",
        "error": error,
    }
    _last_scan = result
    _audit(request, user, "eas_rd_scan", "success" if not error else "error",
           detail={"packages_scanned": len(packages), "findings": len(findings)})
    return result


@router.get("/eas-rd/last-scan")
async def last_eas_rd_scan():
    _require()
    if _last_scan is None:
        return {"scanned_at": None, "findings": [], "note": "No scan run yet — POST /api/vault/eas-rd/scan"}
    return _last_scan


# ══════════════════════════════════════════════════════════════════════════
# Trade Secrets vault
# ══════════════════════════════════════════════════════════════════════════

class VaultItemCreate(BaseModel):
    title: str = Field(..., max_length=256)
    content: str = Field(..., max_length=200_000)
    classification: str = Field(default="TRADE_SECRET")
    allowed_roles: List[str] = Field(default_factory=lambda: ["root_admin"])


@router.post("/items", dependencies=[require_permission("vault:write")])
async def create_vault_item(req: VaultItemCreate, request: Request,
                             user: dict = Depends(get_authenticated_user)):
    _require()
    item_id = str(uuid.uuid4())
    plaintext = req.content.encode("utf-8")
    envelope = _enc.encrypt(plaintext)
    content_hash = hashlib.sha3_256(plaintext).hexdigest()
    _db.vault_insert(item_id, req.title, req.classification, user["user_id"],
                      envelope, content_hash, req.allowed_roles)
    _audit(request, user, "vault_write", "success", item_id, {"title": req.title})
    return {"item_id": item_id, "status": "created", "content_sha3_256": content_hash}


@router.get("/items", dependencies=[require_permission("vault:read")])
async def list_vault_items():
    _require()
    return {"items": _db.vault_list()}


@router.get("/items/{item_id}", dependencies=[require_permission("vault:read")])
async def get_vault_item(item_id: str, request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    item = _db.vault_get(item_id)
    if not item or item.get("status") != "active":
        raise HTTPException(status_code=404, detail="Vault item not found")

    allowed_roles = json.loads(item.get("allowed_roles") or "[]")
    user_roles = set(_db.get_user_roles(user["user_id"]))
    is_owner = item.get("owner_user_id") == user["user_id"]
    if allowed_roles and not (user_roles & set(allowed_roles)) and not is_owner:
        _audit(request, user, "vault_read", "denied", item_id)
        raise HTTPException(status_code=403, detail="Not authorized for this classification level")

    envelope = json.loads(item["ciphertext_envelope"])
    try:
        plaintext = _enc.decrypt(envelope)
    except Exception as e:
        logger.exception("Vault decrypt failed for %s", item_id)
        raise HTTPException(status_code=500, detail=f"Decryption failed: {e}")

    integrity_ok = hashlib.sha3_256(plaintext).hexdigest() == item["content_sha3_256"]
    _audit(request, user, "vault_read", "success", item_id, {"integrity_ok": integrity_ok})
    return {
        "item_id": item_id, "title": item["title"], "classification": item["classification"],
        "content": plaintext.decode("utf-8", errors="replace"),
        "integrity_verified": integrity_ok,
        "created_at": str(item["created_at"]),
    }


@router.delete("/items/{item_id}", dependencies=[require_permission("vault:write")])
async def archive_vault_item(item_id: str, request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    ok = _db.vault_archive(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Vault item not found")
    _audit(request, user, "vault_archive", "success", item_id)
    return {"status": "archived"}
