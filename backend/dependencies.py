"""
backend/dependencies.py
========================
Shared FastAPI auth dependencies for JAKAL v2.6 (Global Settings & Security).

Design — "progressive hardening", not a hard cutover:
  This platform previously shipped with zero authentication on the API
  (every endpoint, including `/api/vm/sandboxes/{name}/exec` — arbitrary
  command execution in a sandbox container — was reachable anonymously).
  A hard cutover to mandatory auth on every route would (a) brick the
  existing zero-config `docker compose up` / `setup-jakal-quick.sh` demo
  flow that `integration.js` drives on first load, and (b) lock operators
  out of their own fresh install before they've created an account.

  So: while the `users` table is empty (a fresh install, or this run
  purely as a local authorized-pentest lab where nobody has bothered to
  create accounts), `require_permission()` is a no-op that logs to
  audit_log and lets the request through. The moment the first user is
  created via POST /api/iam/auth/register, the platform is no longer
  "empty" and every permission-gated route starts enforcing real
  Bearer-JWT auth + RBAC. This mirrors the bootstrap pattern used by
  Kubernetes API servers, most admin panels (e.g. phpMyAdmin's `setup`
  mode), and CI systems: open until the first admin exists, locked after.

  This is a deliberate, documented tradeoff for a security tool primarily
  operated by a single team in a lab/engagement context — not a general
  multi-tenant SaaS auth model. For that, wire `JAKAL_REQUIRE_AUTH=true`
  (see `_bootstrap_mode()` below) to force enforcement even with zero users,
  and terminate TLS in front of this service (see nginx.conf / k8s/).
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "jakal-iam"
ACCESS_TOKEN_TTL_MINUTES = int(os.getenv("JAKAL_JWT_TTL_MINUTES", "60"))


def _jwt_secret() -> str:
    """
    Secret used to sign/verify session JWTs.

    Prefers JAKAL_MASTER_KEY (already required for other secrets in this
    app — see config.py) so operators don't need to manage a second
    secret. Falls back to a process-lifetime random secret so the app
    still boots in dev without any .env configured; that fallback means
    tokens don't survive a process restart, which is intentional (fails
    safe — nobody is silently trusting an unconfigured deployment's old
    hardcoded secret).
    """
    key = os.getenv("JAKAL_MASTER_KEY", "")
    if key:
        return hashlib.sha3_256(key.encode("utf-8")).hexdigest()
    global _EPHEMERAL_SECRET
    try:
        return _EPHEMERAL_SECRET
    except NameError:
        _EPHEMERAL_SECRET = secrets.token_hex(32)
        logger.warning(
            "JAKAL_MASTER_KEY not set — using an ephemeral JWT signing key. "
            "Sessions will not survive a process restart. Set JAKAL_MASTER_KEY "
            "in backend/.env for production/persistent use."
        )
        return _EPHEMERAL_SECRET


def issue_access_token(user_id: str, username: str) -> tuple[str, str, datetime]:
    """Returns (token, session_id, expires_at)."""
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    payload = {
        "iss": JWT_ISSUER,
        "sub": user_id,
        "username": username,
        "jti": session_id,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, session_id, expires_at


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError subclasses on any invalid/expired/tampered token."""
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM], issuer=JWT_ISSUER)


def _bootstrap_mode(db) -> bool:
    """True while auth should be treated as optional (see module docstring)."""
    if os.getenv("JAKAL_REQUIRE_AUTH", "false").lower() == "true":
        return False
    try:
        return db.count_users() == 0
    except Exception:
        # If the IAM tables aren't reachable at all, fail OPEN for read-mostly
        # local-lab usage rather than 500ing every request — but this is only
        # reachable if the DB itself is unavailable, in which case downstream
        # handlers will fail anyway.
        return True


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def get_current_user(request: Request) -> Optional[dict]:
    """
    Resolves the caller from a `Authorization: Bearer <jwt>` header.
    Returns None (not an error) when no/invalid credentials are supplied —
    callers decide whether that's acceptable via require_permission()'s
    bootstrap-mode check. This lets read-only/status endpoints stay
    anonymous-friendly while write endpoints still enforce permissions.
    """
    from database import get_db_manager

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError as e:
        logger.info("Rejected JWT: %s", e)
        return None
    db = get_db_manager()
    if not db.is_session_valid(claims.get("jti", "")):
        return None
    user = db.get_user_by_id(claims["sub"])
    if not user or user.get("status") != "active":
        return None
    return user


def require_permission(permission_key: str):
    """
    Usage: @app.post(..., dependencies=[require_permission("vm:exec")])

    Enforces Bearer-JWT auth + RBAC once the platform has left bootstrap
    mode (see module docstring). Every call — granted, denied, or
    bootstrap-bypassed — is written to the structured audit_log so the
    Auditing tab has a real trail even during the bootstrap window.
    """

    async def _dependency(request: Request):
        from database import get_db_manager

        db = get_db_manager()
        user = await get_current_user(request)
        bootstrap = _bootstrap_mode(db)

        if user is None:
            if bootstrap:
                db.insert_audit_entry({
                    "actor_user_id": None, "actor_label": "anonymous(bootstrap)",
                    "action": permission_key, "resource_type": "endpoint",
                    "resource_id": str(request.url.path), "outcome": "success",
                    "ip_address": _client_ip(request),
                    "detail": {"note": "allowed — no users provisioned yet"},
                })
                return
            db.insert_audit_entry({
                "actor_user_id": None, "actor_label": "anonymous",
                "action": permission_key, "resource_type": "endpoint",
                "resource_id": str(request.url.path), "outcome": "denied",
                "ip_address": _client_ip(request),
                "detail": {"reason": "no/invalid bearer token"},
            })
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. POST /api/iam/auth/login for a session token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_perms = set(db.get_user_permissions(user["user_id"]))
        allowed = permission_key in user_perms or "system:*" in user_perms
        db.insert_audit_entry({
            "actor_user_id": user["user_id"], "actor_label": user["username"],
            "action": permission_key, "resource_type": "endpoint",
            "resource_id": str(request.url.path),
            "outcome": "success" if allowed else "denied",
            "ip_address": _client_ip(request), "detail": {},
        })
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission_key}",
            )

    return Depends(_dependency)


async def get_authenticated_user(request: Request) -> dict:
    """
    Strict dependency (no bootstrap bypass) for endpoints that need to know
    *who* is calling regardless of bootstrap state — e.g. "list my API
    keys", "my profile". Use `require_permission()` instead when the check
    is "is this action allowed", which is bootstrap-aware.
    """
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
