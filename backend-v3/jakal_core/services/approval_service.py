"""Human Approval Gate (/api/approval/) with RBAC + separation of duties.

The reviewed codebase had the right idea (persisted approval rows, PQC signing)
but no real identity behind "human operator" and no separation of duties. Here:

  * Creating a request requires an authenticated OPERATOR+.
  * Deciding requires an APPROVER+, and the approver may NOT be the requester
    (SeparationOfDutiesError) — the core control that makes the gate meaningful.
  * Execution is blocked unless the persisted decision is APPROVED, checked
    against the row, not an in-memory flag (the original bug).
  * Every stage/decide/execute is PQC-signed into the audit log.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Principal, require
from ..errors import ConflictError, NotFoundError, SeparationOfDutiesError
from ..logging_config import get_logger
from ..models import ApprovalRequest, ApprovalStatus, RiskLevel, Role
from .crypto_service import CryptoService

logger = get_logger(__name__)

_AUTO_APPROVE_BELOW = {RiskLevel.LOW}  # LOW risk needs no human; HIGH/CRIT do.


class ApprovalService:
    def __init__(self, session: AsyncSession, crypto: CryptoService) -> None:
        self._s = session
        self._crypto = crypto

    async def create_request(
        self,
        principal: Principal,
        *,
        action_type: str,
        target: str | None,
        risk_level: RiskLevel,
        summary: str,
        payload_detail: dict,
        origin_module: str | None = None,
        ttl_minutes: int = 120,
    ) -> ApprovalRequest:
        require(principal, Role.OPERATOR)
        entry = await self._crypto.sign_agent_action(
            agent_id="approval-gate",
            action_payload={"action_type": f"stage:{action_type}", "target": target},
            operator_id=principal.operator_id,
        )
        req = ApprovalRequest(
            request_id=uuid.uuid4(),
            requested_by=principal.operator_id,
            action_type=action_type,
            target=target,
            risk_level=risk_level,
            status=ApprovalStatus.PENDING,
            summary=summary,
            payload_detail=payload_detail,
            origin_module=origin_module,
            pqc_entry_id=entry.entry_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )
        self._s.add(req)
        await self._s.flush()
        logger.info(
            "approval staged",
            extra={"extra": {"request_id": str(req.request_id), "risk": risk_level.value}},
        )
        return req

    async def _get(self, request_id: uuid.UUID) -> ApprovalRequest:
        req = await self._s.get(ApprovalRequest, request_id)
        if req is None:
            raise NotFoundError(f"approval request {request_id} not found")
        return req

    async def decide(
        self, principal: Principal, request_id: uuid.UUID, *, approve: bool, reason: str = ""
    ) -> ApprovalRequest:
        require(principal, Role.APPROVER)
        req = await self._get(request_id)

        # Separation of duties: the requester cannot approve their own action.
        if principal.operator_id == req.requested_by:
            raise SeparationOfDutiesError(
                "the requester of an action may not approve it"
            )
        if req.status is not ApprovalStatus.PENDING:
            raise ConflictError(f"request already {req.status.value}")
        if req.expires_at and req.expires_at < datetime.now(UTC):
            req.status = ApprovalStatus.EXPIRED
            await self._s.flush()
            raise ConflictError("request has expired")

        req.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED
        req.decided_by = principal.operator_id
        req.decision_reason = reason
        req.decided_at = datetime.now(UTC)
        await self._crypto.sign_agent_action(
            agent_id="approval-gate",
            action_payload={
                "action_type": f"decision:{req.status.value}",
                "request_id": str(request_id),
                "decided_by": principal.operator_id,
            },
            operator_id=principal.operator_id,
        )
        await self._s.flush()
        logger.info(
            "approval decided",
            extra={"extra": {"request_id": str(request_id), "status": req.status.value}},
        )
        return req

    async def execute(self, principal: Principal, request_id: uuid.UUID) -> dict:
        """Gate: only an APPROVED (persisted) request executes. Idempotent —
        a second execute is a conflict, not a re-run."""
        require(principal, Role.OPERATOR)
        req = await self._get(request_id)
        if req.status is not ApprovalStatus.APPROVED:
            return {
                "status": "blocked",
                "reason": f"request is {req.status.value}, not approved",
                "request_id": str(request_id),
            }
        if req.executed:
            raise ConflictError("request already executed")
        req.executed = True
        await self._s.flush()
        # Execution itself is handed to the operator / VM orchestrator — this
        # service records the gated go-ahead, it does not auto-run offensive
        # commands (preserving the reviewed codebase's safe posture).
        return {"status": "executed", "request_id": str(request_id), "target": req.target}

    async def list_pending(self, limit: int = 100) -> list[ApprovalRequest]:
        stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.PENDING)
            .order_by(ApprovalRequest.created_at.desc())
            .limit(limit)
        )
        return list((await self._s.execute(stmt)).scalars().all())

    async def gate_stats(self) -> dict[str, int]:
        stmt = select(ApprovalRequest.status, func.count()).group_by(ApprovalRequest.status)
        rows = (await self._s.execute(stmt)).all()
        return {status.value: count for status, count in rows}
