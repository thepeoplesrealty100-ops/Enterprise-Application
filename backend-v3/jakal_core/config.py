"""Typed, environment-profiled settings with fail-fast secret validation.

Resolves the boot-fragility finding (GAP-04) and the ephemeral-key finding
(GAP-07): optional integrations degrade to a clearly-signalled disabled state
rather than crashing import, while genuinely required secrets are asserted at
startup in the ``prod`` profile only.
"""
from __future__ import annotations

import secrets
from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Profile(str, Enum):
    DEV = "dev"
    TEST = "test"
    STAGE = "stage"
    PROD = "prod"


class Settings(BaseSettings):
    """All runtime configuration. Reads env vars prefixed ``JAKAL_``."""

    model_config = SettingsConfigDict(
        env_prefix="JAKAL_", env_file=".env", extra="ignore", case_sensitive=False
    )

    profile: Profile = Profile.DEV

    # ── Database ────────────────────────────────────────────────────────────
    # Async driver URLs. Prod expects postgresql+asyncpg://…; tests use
    # sqlite+aiosqlite:///:memory: via the settings override in conftest.
    database_url: str = "sqlite+aiosqlite:///./jakal_v3.db"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_echo: bool = False

    # ── Auth (GAP-01) ───────────────────────────────────────────────────────
    jwt_algorithm: Literal["HS256", "RS256"] = "HS256"
    jwt_secret: str = Field(default="")           # HS256 shared secret
    jwt_public_key: str = Field(default="")       # RS256 PEM (verify side)
    jwt_issuer: str = "jakal-idp"
    jwt_audience: str = "jakal-api"

    # ── Crypto (GAP-05 / GAP-07) ────────────────────────────────────────────
    # strict = require the PQC backend AND both hybrid signatures to verify.
    crypto_strict: bool = False
    master_key: str = Field(default="")           # KEK / envelope root

    # ── Optional integrations — never block startup (GAP-04) ────────────────
    llm_engine: Literal["disabled", "claude", "ollama"] = "disabled"
    claude_api_key: str = ""

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        if v.startswith("postgresql://"):
            # A sync URL on an async engine is a silent footgun — correct it loudly.
            raise ValueError(
                "database_url must use an async driver "
                "(postgresql+asyncpg://… or sqlite+aiosqlite://…)"
            )
        return v

    @model_validator(mode="after")
    def _prod_requires_secrets(self) -> Settings:
        """Fail fast in prod when load-bearing secrets are absent."""
        if self.profile is Profile.PROD:
            missing: list[str] = []
            if self.jwt_algorithm == "HS256" and not self.jwt_secret:
                missing.append("JAKAL_JWT_SECRET")
            if self.jwt_algorithm == "RS256" and not self.jwt_public_key:
                missing.append("JAKAL_JWT_PUBLIC_KEY")
            if not self.master_key:
                missing.append("JAKAL_MASTER_KEY")
            if not self.crypto_strict:
                missing.append("JAKAL_CRYPTO_STRICT=true")
            if missing:
                raise RuntimeError(
                    "prod profile is missing required configuration: "
                    + ", ".join(missing)
                )
        # In non-prod, synthesize an ephemeral JWT secret so the app is usable
        # locally — but never in prod (guarded above).
        if not self.jwt_secret and self.jwt_algorithm == "HS256":
            object.__setattr__(self, "jwt_secret", secrets.token_urlsafe(48))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
