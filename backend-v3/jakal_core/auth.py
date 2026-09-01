"""Identity + RBAC gate (GAP-01).

The single most important change from the reviewed codebase: ``operator_id`` is
derived from a cryptographically verified bearer token, never from the request
body. A FastAPI app wires ``require_role(...)`` as a router dependency; the pure
token-verification logic lives here so it is unit-testable without a running
server.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import jwt

from .config import Settings, get_settings
from .errors import AuthenticationError, AuthorizationError
from .models import Role

# Role ordering for "at least this role" checks.
_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.OPERATOR: 1,
    Role.APPROVER: 2,
    Role.ADMIN: 3,
}


@dataclass(frozen=True)
class Principal:
    operator_id: str
    role: Role
    email: str | None = None

    def has_at_least(self, role: Role) -> bool:
        return _RANK[self.role] >= _RANK[role]


def _verify_key(settings: Settings) -> str:
    if settings.jwt_algorithm == "HS256":
        return settings.jwt_secret
    return settings.jwt_public_key


def decode_token(token: str, settings: Settings | None = None) -> Principal:
    """Verify a JWT and return the authenticated principal.

    Raises ``AuthenticationError`` on any signature/expiry/claim problem — the
    API maps that to 401. Never trusts unsigned or ``alg=none`` tokens.
    """
    settings = settings or get_settings()
    try:
        claims = jwt.decode(
            token,
            _verify_key(settings),
            algorithms=[settings.jwt_algorithm],  # pinned — blocks alg confusion
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError(f"invalid token: {exc}") from exc

    role_raw = claims.get("role")
    try:
        role = Role(role_raw)
    except ValueError as exc:
        raise AuthenticationError(f"unknown role claim: {role_raw!r}") from exc

    return Principal(
        operator_id=str(claims["sub"]), role=role, email=claims.get("email")
    )


def require(principal: Principal, minimum: Role) -> Principal:
    if not principal.has_at_least(minimum):
        raise AuthorizationError(
            f"role '{principal.role.value}' is below required '{minimum.value}'"
        )
    return principal


def issue_token(
    operator_id: str,
    role: Role,
    *,
    settings: Settings | None = None,
    ttl_seconds: int = 3600,
    email: str | None = None,
    expired: bool = False,
) -> str:
    """Mint a token. Belongs to the IdP in production; provided here so tests
    and local dev can exercise the gate. ``expired=True`` is a test affordance.
    """
    settings = settings or get_settings()
    now = datetime.now(UTC).timestamp()
    exp = now - 60 if expired else now + ttl_seconds
    key = settings.jwt_secret if settings.jwt_algorithm == "HS256" else settings.jwt_public_key
    payload = {
        "sub": operator_id,
        "role": role.value,
        "email": email,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now),
        "exp": int(exp),
    }
    return jwt.encode(payload, key, algorithm=settings.jwt_algorithm)
