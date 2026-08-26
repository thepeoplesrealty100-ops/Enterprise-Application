"""Test harness: an isolated database PER TEST.

This is the fix for GAP-03's non-isolation. Each test gets a fresh SQLite file,
a fresh engine, and a fresh schema built from the models — no shared on-disk
state, no module-level singletons leaking rows between tests. The same ORM code
runs on Postgres in production.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

# Configure BEFORE importing app modules so get_settings() reads test values.
os.environ["JAKAL_PROFILE"] = "test"
os.environ["JAKAL_JWT_ALGORITHM"] = "HS256"
os.environ["JAKAL_JWT_SECRET"] = "test-secret-please-rotate-0123456789-abcdefghij"
os.environ["JAKAL_MASTER_KEY"] = "test-master-key-0123456789abcdef"

from jakal_core import auth, config, db  # noqa: E402
from jakal_core.crypto.pqc import HybridSigner  # noqa: E402
from jakal_core.models import Operator, Role  # noqa: E402
from jakal_core.services.approval_service import ApprovalService  # noqa: E402
from jakal_core.services.ares_service import AresService  # noqa: E402
from jakal_core.services.canvas_service import CanvasService  # noqa: E402
from jakal_core.services.crypto_service import CryptoService  # noqa: E402
from jakal_core.services.quantum_service import QuantumJobService  # noqa: E402


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncIterator:
    dbfile = tmp_path / f"t_{uuid.uuid4().hex}.db"
    os.environ["JAKAL_DATABASE_URL"] = f"sqlite+aiosqlite:///{dbfile}"
    config.get_settings.cache_clear()
    await db.dispose_engine()
    db.init_engine(config.get_settings())
    await db.create_all()

    maker = db.get_sessionmaker()
    async with maker() as s:
        yield s
        await s.rollback()
    await db.dispose_engine()


@pytest.fixture
def signer() -> HybridSigner:
    return HybridSigner(strict=False)


@pytest.fixture
def strict_signer() -> HybridSigner:
    return HybridSigner(strict=True)


@pytest.fixture
def crypto(session, signer) -> CryptoService:
    return CryptoService(session, signer, master_key=config.get_settings().master_key)


@pytest.fixture
def approvals(session, crypto) -> ApprovalService:
    return ApprovalService(session, crypto)


@pytest.fixture
def ares(session) -> AresService:
    return AresService(session)


@pytest.fixture
def canvas(session) -> CanvasService:
    return CanvasService(session)


@pytest.fixture
def quantum(session) -> QuantumJobService:
    return QuantumJobService(session)


@pytest_asyncio.fixture
async def sessionmaker_(session):
    """The process sessionmaker, for tests that need many concurrent sessions.

    Depends on ``session`` so the per-test database and its engine are created
    and bound to THIS test's event loop before the maker is handed out — without
    that dependency a test would reuse a disposed engine from a prior test's
    loop (RuntimeError: bound to a different event loop).
    """
    return db.get_sessionmaker()


@pytest.fixture
def principals():
    """Three distinct authenticated principals for separation-of-duties tests."""
    return {
        "operator": auth.Principal("op-alice", Role.OPERATOR, "alice@x"),
        "approver": auth.Principal("ap-bob", Role.APPROVER, "bob@x"),
        "admin": auth.Principal("ad-carol", Role.ADMIN, "carol@x"),
        "viewer": auth.Principal("vi-dan", Role.VIEWER, "dan@x"),
    }


@pytest_asyncio.fixture
async def seed_operators(session):
    for pid, role in [("op-alice", Role.OPERATOR), ("ap-bob", Role.APPROVER),
                      ("ad-carol", Role.ADMIN), ("vi-dan", Role.VIEWER)]:
        session.add(Operator(operator_id=pid, email=f"{pid}@x", role=role, active=True))
    await session.flush()
