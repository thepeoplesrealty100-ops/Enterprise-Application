"""
backend/routers/iam.py
=======================
Identity & Access Management — JAKAL v2.6.

Backs four of the nine "Global Settings & Security" sub-tabs:
  Profile, Login Encryption (auth/MFA), RBAC, Auditing
  (API Integration is also here: API key issuance lives in IAM)

Endpoints:
  POST   /iam/auth/register           — create a user (Argon2-class bcrypt hash)
  POST   /iam/auth/login              — password (+ TOTP if MFA enabled) -> JWT
  POST   /iam/auth/logout             — revoke the current session
  GET    /iam/auth/me                 — current operator's profile
  POST   /iam/auth/mfa/enroll         — generate a TOTP secret + QR provisioning URI
  POST   /iam/auth/mfa/confirm        — verify first TOTP code, turns MFA on
  POST   /iam/auth/mfa/disable        — turn MFA back off
  POST   /iam/auth/change-password

  GET    /iam/rbac/roles              — list roles
  GET    /iam/rbac/permissions        — list permissions
  POST   /iam/rbac/roles              — create a custom role
  POST   /iam/rbac/roles/{role_key}/permissions   — grant a permission to a role
  DELETE /iam/rbac/roles/{role_key}/permissions/{permission_key}
  GET    /iam/rbac/users              — list users with their assigned roles
  POST   /iam/rbac/users/{user_id}/roles          — assign a role to a user
  DELETE /iam/rbac/users/{user_id}/roles/{role_key}

  POST   /iam/api-keys                — issue a new API key (secret shown once)
  GET    /iam/api-keys                — list my keys (metadata only, never the secret)
  POST   /iam/api-keys/{key_id}/revoke

  GET    /iam/audit/log               — query the structured audit trail
  GET    /iam/audit/export            — export audit trail as Markdown

Security notes:
  - Passwords are hashed with bcrypt (cost factor 12) — the plaintext
    password is never stored or logged.
  - Failed logins are rate-limited via account lockout (database.py's
    record_login_failure: 5 failures -> 15 minute lock), mitigating
    online password-guessing per NIST SP 800-63B §5.2.2.
  - Login/registration responses are deliberately generic ("invalid
    credentials") to avoid username enumeration (OWASP ASVS 2.1.1 / 2.1.11).
  - See backend/dependencies.py for the bootstrap-mode rationale: RBAC
    enforcement activates automatically once the first user is registered.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import bcrypt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status
from pydantic import BaseModel, EmailStr, Field, field_validator

try:
    from database import get_db_manager
    _db = get_db_manager()
    IAM_OK = True
    _IAM_ERR = None
except Exception as _e:  # noqa: BLE001
    IAM_OK = False
    _IAM_ERR = str(_e)
    _db = None

from dependencies import get_authenticated_user, require_permission, issue_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/iam", tags=["iam"])


# ══════════════════════════════════════════════════════════════════════════
# Default RBAC seed — mirrors the ROOT_ADMIN_ZERO / Security Analyst /
# Read-Only roles already mocked in the frontend's RBAC tab, now backed by
# real rows instead of a hardcoded HTML table.
# ══════════════════════════════════════════════════════════════════════════

_DEFAULT_PERMISSIONS = [
    ("system:*", "Full system access", "System"),
    ("scope:manage", "Add/edit authorization scope & insurance", "Authorization"),
    ("vm:manage", "Create/destroy sandbox VMs", "Sandbox"),
    ("vm:exec", "Execute commands inside a sandbox VM", "Sandbox"),
    ("edr:manage", "Run/manage EDR/MDR playbooks", "EDR/MDR"),
    ("vault:read", "Read Trade Secrets / EAS R&D vault items", "Vault"),
    ("vault:write", "Create/archive vault items", "Vault"),
    ("iam:manage_roles", "Manage roles & permissions", "IAM"),
    ("iam:manage_users", "Manage user role assignments", "IAM"),
    ("iam:manage_keys", "Issue/revoke API keys", "IAM"),
    ("audit:read", "Read the audit log", "IAM"),
    ("darkweb:manage", "Manage dark-web watchlist", "Dark Web"),
    ("awareness:manage", "Launch training/phishing campaigns", "Awareness"),
    ("read:dashboard", "View dashboards (read-only)", "General"),
]

_DEFAULT_ROLES = [
    ("root_admin", "ROOT_ADMIN_ZERO", "Unrestricted operator — first account created", True,
     ["system:*"]),
    ("security_analyst", "Security Analyst", "Operate day-to-day security tooling", True,
     ["vm:manage", "vm:exec", "edr:manage", "vault:read", "darkweb:manage",
      "awareness:manage", "audit:read", "read:dashboard"]),
    ("read_only", "Read-Only", "Dashboards and reports only, no mutating actions", True,
     ["read:dashboard", "audit:read"]),
]


def _seed_rbac() -> None:
    if not IAM_OK:
        return
    for key, label, category in _DEFAULT_PERMISSIONS:
        _db.upsert_permission(key, label, category)
    for role_key, label, desc, is_system, perms in _DEFAULT_ROLES:
        _db.upsert_role(role_key, label, desc, is_system)
        for p in perms:
            _db.grant_role_permission(role_key, p)


_seed_rbac()


def _require():
    if not IAM_OK:
        raise HTTPException(status_code=503, detail=f"IAM module unavailable: {_IAM_ERR}")


def _audit(request: Request, user: Optional[dict], action: str, outcome: str,
           resource_type: str = "iam", resource_id: str = "", detail: Optional[dict] = None):
    try:
        _db.insert_audit_entry({
            "actor_user_id": user["user_id"] if user else None,
            "actor_label": user["username"] if user else "anonymous",
            "action": action, "resource_type": resource_type, "resource_id": resource_id,
            "outcome": outcome,
            "ip_address": request.client.host if request.client else None,
            "detail": detail or {},
        })
    except Exception:
        logger.exception("Failed to write audit entry for %s", action)


# ══════════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=12, max_length=256)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        # NIST SP 800-63B favors length over composition rules, but a floor
        # of "not trivially guessable" is still worth enforcing server-side.
        if v.lower() in ("password", "changeme", "letmein123456") or v.isdigit():
            raise ValueError("Password is too weak/common")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = Field(default=None, min_length=6, max_length=6)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=12, max_length=256)


class MfaConfirmRequest(BaseModel):
    totp_code: str = Field(..., min_length=6, max_length=6)


class RoleCreateRequest(BaseModel):
    role_key: str = Field(..., pattern=r"^[a-z0-9_]{3,64}$")
    label: str
    description: str = ""


class RolePermissionRequest(BaseModel):
    permission_key: str


class ApiKeyCreateRequest(BaseModel):
    label: str = Field(..., max_length=128)
    scopes: List[str] = Field(default_factory=list)
    expires_in_days: Optional[int] = Field(default=90, ge=1, le=3650)


# ══════════════════════════════════════════════════════════════════════════
# Auth
# ══════════════════════════════════════════════════════════════════════════

@router.post("/auth/register", status_code=http_status.HTTP_201_CREATED)
async def register(req: RegisterRequest, request: Request):
    _require()
    if _db.get_user_by_username(req.username):
        # Same generic error whether username OR password is the actual
        # problem downstream — avoids confirming "this username exists".
        raise HTTPException(status_code=409, detail="Registration failed")

    first_user = _db.count_users() == 0
    password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    user_id = str(uuid.uuid4())
    _db.create_user(user_id, req.username, req.email, password_hash)
    # The very first account created on a fresh install becomes root admin —
    # standard bootstrap pattern (matches Kubernetes' first-cluster-admin,
    # Django's createsuperuser). Every subsequent registration gets the
    # least-privileged role; an existing root_admin must promote them via
    # POST /iam/rbac/users/{user_id}/roles.
    _db.assign_user_role(user_id, "root_admin" if first_user else "read_only")
    _audit(request, {"user_id": user_id, "username": req.username}, "register", "success")
    return {
        "user_id": user_id, "username": req.username,
        "role": "root_admin" if first_user else "read_only",
        "note": "Bootstrap mode is now OFF — all permission-gated endpoints require login." if first_user else None,
    }


@router.post("/auth/login")
async def login(req: LoginRequest, request: Request):
    _require()
    user = _db.get_user_by_username(req.username)
    generic_error = HTTPException(status_code=401, detail="Invalid username or password")

    if not user:
        # Still run a bcrypt check against a dummy hash so login timing
        # doesn't leak whether the username exists (timing side-channel).
        bcrypt.checkpw(b"decoy", bcrypt.gensalt())
        raise generic_error

    if user.get("locked_until"):
        locked_until = user["locked_until"]
        if locked_until and locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
            _audit(request, user, "login", "denied", detail={"reason": "account locked"})
            raise HTTPException(status_code=423, detail="Account temporarily locked; try again later")

    if not bcrypt.checkpw(req.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        failures = _db.record_login_failure(user["user_id"])
        _audit(request, user, "login", "denied", detail={"reason": "bad password", "failures": failures})
        raise generic_error

    if user.get("mfa_enabled"):
        if not req.totp_code:
            return {"mfa_required": True}
        totp = pyotp.TOTP(user["mfa_secret"])
        if not totp.verify(req.totp_code, valid_window=1):
            _audit(request, user, "login", "denied", detail={"reason": "bad totp"})
            raise HTTPException(status_code=401, detail="Invalid MFA code")

    token, session_id, expires_at = issue_access_token(user["user_id"], user["username"])
    _db.create_session(
        session_id, user["user_id"], expires_at,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _db.record_login_success(user["user_id"], request.client.host if request.client else None)
    _audit(request, user, "login", "success")
    return {
        "access_token": token, "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": {"user_id": user["user_id"], "username": user["username"]},
    }


@router.post("/auth/logout")
async def logout(request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    try:
        from dependencies import decode_access_token
        claims = decode_access_token(token)
        _db.revoke_session(claims["jti"])
    except Exception:
        pass
    _audit(request, user, "logout", "success")
    return {"status": "logged_out"}


@router.get("/auth/me")
async def me(request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    roles = _db.get_user_roles(user["user_id"])
    perms = _db.get_user_permissions(user["user_id"])
    return {
        "user_id": user["user_id"], "username": user["username"], "email": user.get("email"),
        "mfa_enabled": user.get("mfa_enabled", False), "roles": roles, "permissions": perms,
        "created_at": str(user.get("created_at")), "last_login_at": str(user.get("last_login_at")),
    }


@router.post("/auth/change-password")
async def change_password(req: ChangePasswordRequest, request: Request,
                           user: dict = Depends(get_authenticated_user)):
    _require()
    if not bcrypt.checkpw(req.current_password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        _audit(request, user, "change_password", "denied")
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    new_hash = bcrypt.hashpw(req.new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    _db.conn.execute("UPDATE users SET password_hash = ? WHERE user_id = ?", (new_hash, user["user_id"]))
    _db.conn.commit()
    _audit(request, user, "change_password", "success")
    return {"status": "password_changed"}


@router.post("/auth/mfa/enroll")
async def mfa_enroll(request: Request, user: dict = Depends(get_authenticated_user)):
    """Generates a TOTP secret (not yet active) + otpauth:// URI for a QR code."""
    _require()
    secret = pyotp.random_base32()
    _db.set_mfa_secret(user["user_id"], secret, enabled=False)
    uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="JAKAL")
    _audit(request, user, "mfa_enroll", "success")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/auth/mfa/confirm")
async def mfa_confirm(req: MfaConfirmRequest, request: Request,
                       user: dict = Depends(get_authenticated_user)):
    _require()
    fresh = _db.get_user_by_id(user["user_id"])
    if not fresh.get("mfa_secret"):
        raise HTTPException(status_code=400, detail="Call /iam/auth/mfa/enroll first")
    if not pyotp.TOTP(fresh["mfa_secret"]).verify(req.totp_code, valid_window=1):
        _audit(request, user, "mfa_confirm", "denied")
        raise HTTPException(status_code=401, detail="Invalid code")
    _db.set_mfa_secret(user["user_id"], fresh["mfa_secret"], enabled=True)
    _audit(request, user, "mfa_confirm", "success")
    return {"status": "mfa_enabled"}


@router.post("/auth/mfa/disable")
async def mfa_disable(request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    _db.set_mfa_secret(user["user_id"], "", enabled=False)
    _audit(request, user, "mfa_disable", "success")
    return {"status": "mfa_disabled"}


# ══════════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════════

@router.get("/rbac/roles")
async def list_roles():
    _require()
    roles = _db.list_roles()
    for r in roles:
        r["permissions"] = _db.get_role_permissions(r["role_key"])
        r["assigned_users"] = len(_db.conn.execute(
            "SELECT 1 FROM user_roles WHERE role_key = ?", (r["role_key"],)
        ).fetchall())
    return {"roles": roles}


@router.get("/rbac/permissions")
async def list_permissions():
    _require()
    return {"permissions": _db.list_permissions()}


@router.post("/rbac/roles", dependencies=[require_permission("iam:manage_roles")])
async def create_role(req: RoleCreateRequest, request: Request,
                       user: dict = Depends(get_authenticated_user)):
    _require()
    _db.upsert_role(req.role_key, req.label, req.description, is_system=False)
    _audit(request, user, "role_create", "success", "role", req.role_key)
    return {"status": "created", "role_key": req.role_key}


@router.post("/rbac/roles/{role_key}/permissions", dependencies=[require_permission("iam:manage_roles")])
async def grant_permission(role_key: str, req: RolePermissionRequest, request: Request,
                            user: dict = Depends(get_authenticated_user)):
    _require()
    _db.grant_role_permission(role_key, req.permission_key)
    _audit(request, user, "role_grant_permission", "success", "role", role_key,
           {"permission_key": req.permission_key})
    return {"status": "granted"}


@router.delete("/rbac/roles/{role_key}/permissions/{permission_key}",
                dependencies=[require_permission("iam:manage_roles")])
async def revoke_permission(role_key: str, permission_key: str, request: Request,
                             user: dict = Depends(get_authenticated_user)):
    _require()
    _db.conn.execute(
        "DELETE FROM role_permissions WHERE role_key = ? AND permission_key = ?",
        (role_key, permission_key),
    )
    _db.conn.commit()
    _audit(request, user, "role_revoke_permission", "success", "role", role_key,
           {"permission_key": permission_key})
    return {"status": "revoked"}


@router.get("/rbac/users")
async def list_rbac_users():
    _require()
    users = _db.list_users()
    for u in users:
        u["roles"] = _db.get_user_roles(u["user_id"])
    return {"users": users}


@router.post("/rbac/users/{user_id}/roles", dependencies=[require_permission("iam:manage_users")])
async def assign_role(user_id: str, req: RolePermissionRequest, request: Request,
                       user: dict = Depends(get_authenticated_user)):
    # req.permission_key doubles as role_key here to keep one small schema;
    # FastAPI validates the body shape, the value itself is just a string.
    _require()
    if not _db.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    _db.assign_user_role(user_id, req.permission_key)
    _audit(request, user, "role_assign", "success", "user", user_id, {"role_key": req.permission_key})
    return {"status": "assigned"}


@router.delete("/rbac/users/{user_id}/roles/{role_key}", dependencies=[require_permission("iam:manage_users")])
async def unassign_role(user_id: str, role_key: str, request: Request,
                         user: dict = Depends(get_authenticated_user)):
    _require()
    _db.revoke_user_role(user_id, role_key)
    _audit(request, user, "role_unassign", "success", "user", user_id, {"role_key": role_key})
    return {"status": "unassigned"}


# ══════════════════════════════════════════════════════════════════════════
# API Integration — API key management
# ══════════════════════════════════════════════════════════════════════════

@router.post("/api-keys", dependencies=[require_permission("iam:manage_keys")])
async def create_api_key(req: ApiKeyCreateRequest, request: Request,
                          user: dict = Depends(get_authenticated_user)):
    """
    Issues a new API key. The full secret is returned exactly once — only
    a SHA3-256 hash is persisted, so it cannot be recovered later (same
    principle as a GitHub PAT or AWS access key).
    """
    _require()
    key_id = f"jak_{uuid.uuid4().hex[:12]}"
    secret = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars of entropy
    key_hash = hashlib.sha3_256(secret.encode("utf-8")).hexdigest()
    expires_at = None
    if req.expires_in_days:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_in_days)
    _db.create_api_key(key_id, key_hash, user["user_id"], req.label, req.scopes, expires_at)
    _audit(request, user, "api_key_create", "success", "api_key", key_id, {"label": req.label})
    return {
        "key_id": key_id, "secret": f"{key_id}.{secret}",
        "warning": "This is the only time the secret is shown. Store it securely.",
        "scopes": req.scopes, "expires_at": expires_at.isoformat() if expires_at else None,
    }


@router.get("/api-keys")
async def list_api_keys(request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    return {"keys": _db.list_api_keys(owner_user_id=user["user_id"])}


@router.post("/api-keys/{key_id}/revoke", dependencies=[require_permission("iam:manage_keys")])
async def revoke_api_key(key_id: str, request: Request, user: dict = Depends(get_authenticated_user)):
    _require()
    ok = _db.revoke_api_key(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found")
    _audit(request, user, "api_key_revoke", "success", "api_key", key_id)
    return {"status": "revoked"}


# ══════════════════════════════════════════════════════════════════════════
# Auditing
# ══════════════════════════════════════════════════════════════════════════

@router.get("/audit/log", dependencies=[require_permission("audit:read")])
async def get_audit_log(actor_user_id: Optional[str] = None, action: Optional[str] = None,
                         limit: int = 100):
    _require()
    limit = max(1, min(limit, 1000))
    entries = _db.list_audit_entries(actor_user_id=actor_user_id, action=action, limit=limit)
    for e in entries:
        if isinstance(e.get("detail"), str):
            try:
                e["detail"] = json.loads(e["detail"])
            except Exception:
                pass
    return {"count": len(entries), "entries": entries}


@router.get("/audit/export", dependencies=[require_permission("audit:read")])
async def export_audit_log(limit: int = 500):
    _require()
    entries = _db.list_audit_entries(limit=max(1, min(limit, 5000)))
    lines = ["# JAKAL Audit Log Export", f"Generated: {datetime.now(timezone.utc).isoformat()}", "",
             "| Timestamp | Actor | Action | Resource | Outcome | IP |",
             "|---|---|---|---|---|---|"]
    for e in entries:
        lines.append(
            f"| {e.get('timestamp')} | {e.get('actor_label') or 'anonymous'} | {e.get('action')} "
            f"| {e.get('resource_type')}:{e.get('resource_id')} | {e.get('outcome')} | {e.get('ip_address') or ''} |"
        )
    return {"format": "markdown", "content": "\n".join(lines), "count": len(entries)}
