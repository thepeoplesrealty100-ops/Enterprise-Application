"""Quantum job queue (/api/quantum/, /api/qaip/).

A bounded, status-tracked job queue. Enqueue is cheap; a worker drains the
queue with a concurrency cap so a burst of submissions cannot exhaust the
executor. The actual circuit execution is delegated to the Qiskit engine in
production; here the queue's state machine and back-pressure are what matter.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..logging_config import get_logger
from ..models import JobStatus, QuantumJob

logger = get_logger(__name__)


class QuantumJobService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def enqueue(self, *, circuit_name: str, shots: int, submitted_by: str) -> QuantumJob:
        if shots <= 0 or shots > 100_000:
            raise ValueError("shots must be in 1..100000")
        job = QuantumJob(
            job_id=uuid.uuid4(),
            circuit_name=circuit_name,
            shots=shots,
            submitted_by=submitted_by,
            status=JobStatus.QUEUED,
        )
        self._s.add(job)
        await self._s.flush()
        return job

    async def queue_depth(self) -> int:
        return int(
            (
                await self._s.execute(
                    select(func.count()).select_from(QuantumJob).where(
                        QuantumJob.status == JobStatus.QUEUED
                    )
                )
            ).scalar_one()
        )


async def drain_queue(
    maker: async_sessionmaker[AsyncSession], *, max_concurrency: int = 4
) -> int:
    """Worker: run all QUEUED jobs with a bounded concurrency. Returns the count
    processed. Each job runs in its own session so failures are isolated and a
    hung job cannot poison a shared transaction."""
    async with maker() as s:
        job_ids = list(
            (
                await s.execute(select(QuantumJob.job_id).where(QuantumJob.status == JobStatus.QUEUED))
            ).scalars().all()
        )

    sem = asyncio.Semaphore(max_concurrency)

    async def _run(job_id: uuid.UUID) -> None:
        async with sem, maker() as s:
            job = await s.get(QuantumJob, job_id)
            if job is None or job.status is not JobStatus.QUEUED:
                return
            job.status = JobStatus.RUNNING
            await s.commit()
            try:
                # Placeholder for Qiskit execution — deterministic stub result.
                result = {"counts": {"0" * 3: job.shots // 2, "1" * 3: job.shots - job.shots // 2}}
                job.status = JobStatus.COMPLETED
                job.result = result
                job.completed_at = datetime.now(UTC)
            except Exception as exc:  # pragma: no cover - defensive
                job.status = JobStatus.FAILED
                job.error = str(exc)
            await s.commit()

    await asyncio.gather(*(_run(jid) for jid in job_ids))
    return len(job_ids)
