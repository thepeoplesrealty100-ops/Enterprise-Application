"""Agentic Canvas patch pipeline (/api/canvas/) with real rollback.

A patch task is created in AWAITING_APPROVAL and cannot progress until its
linked approval row is APPROVED (checked against the DB, not a flag). Progress
advances toward 100; a failure at any point rolls the task back to a recorded
ROLLED_BACK state. Deployment execution is delegated (Ansible/SSM/Docker in
production); this service owns the gated state machine.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Principal, require
from ..errors import ConflictError, NotFoundError
from ..logging_config import get_logger
from ..models import (
    ApprovalRequest,
    ApprovalStatus,
    RemediationTask,
    Role,
    TaskStatus,
)

logger = get_logger(__name__)


class CanvasService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create_task(
        self, principal: Principal, *, target_ip: str, patch_id: str, approval_request_id: uuid.UUID
    ) -> RemediationTask:
        require(principal, Role.OPERATOR)
        task = RemediationTask(
            task_id=uuid.uuid4(),
            target_machine_ip=target_ip,
            patch_id=patch_id,
            approval_request_id=approval_request_id,
            status=TaskStatus.AWAITING_APPROVAL,
            deployment_progress=0,
        )
        self._s.add(task)
        await self._s.flush()
        return task

    async def _get(self, task_id: uuid.UUID) -> RemediationTask:
        task = await self._s.get(RemediationTask, task_id)
        if task is None:
            raise NotFoundError(f"task {task_id} not found")
        return task

    async def _is_approved(self, approval_request_id: uuid.UUID) -> bool:
        status = (
            await self._s.execute(
                select(ApprovalRequest.status).where(
                    ApprovalRequest.request_id == approval_request_id
                )
            )
        ).scalar_one_or_none()
        return status is ApprovalStatus.APPROVED

    async def advance(self, task_id: uuid.UUID, progress: int) -> RemediationTask:
        task = await self._get(task_id)
        if task.status in (TaskStatus.ROLLED_BACK, TaskStatus.FAILED, TaskStatus.COMPLETED):
            raise ConflictError(f"task is terminal ({task.status.value})")
        if not await self._is_approved(task.approval_request_id):
            raise ConflictError("cannot advance — approval not granted")
        progress = max(0, min(100, progress))
        task.deployment_progress = progress
        task.status = TaskStatus.COMPLETED if progress >= 100 else TaskStatus.IN_PROGRESS
        await self._s.flush()
        return task

    async def rollback(self, task_id: uuid.UUID, reason: str) -> RemediationTask:
        """Roll a task back. Records the reason and resets progress. A completed
        task can still be rolled back (patch caused a regression)."""
        task = await self._get(task_id)
        task.status = TaskStatus.ROLLED_BACK
        task.rollback_reason = reason
        task.deployment_progress = 0
        await self._s.flush()
        logger.info("patch rolled back", extra={"extra": {"task_id": str(task_id), "reason": reason}})
        return task
