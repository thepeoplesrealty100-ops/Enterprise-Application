"""Async engine, session factory, and the single session-per-request dependency.

This replaces the 15 module-level ``DuckDBManager()`` singletons (GAP-02). The
same code runs on Postgres (``postgresql+asyncpg``) in production and on
SQLite (``sqlite+aiosqlite``) under test — there is no engine-specific SQL in
the models, so the test database is a faithful stand-in for the schema.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base for every model."""


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs(settings: Settings) -> dict[str, Any]:
    # SQLite (aiosqlite) does not accept pool sizing args; Postgres does.
    if settings.database_url.startswith("sqlite"):
        return {"echo": settings.db_echo}
    return {
        "echo": settings.db_echo,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
    }


def init_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create the process-wide engine + sessionmaker (idempotent)."""
    global _engine, _sessionmaker
    settings = settings or get_settings()
    if _engine is None:
        _engine = create_async_engine(settings.database_url, **_engine_kwargs(settings))
        _sessionmaker = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one transaction-scoped session per request.

    Commits on success, rolls back on any exception, always closes.
    """
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create schema from the models. Used by tests and dev bootstrap only;
    production migrates with Alembic."""
    engine = init_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
