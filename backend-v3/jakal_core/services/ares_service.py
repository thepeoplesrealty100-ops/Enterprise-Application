"""Ares unified control plane (/api/ares/) — a derived read model.

Owns no data of its own. The global matrix summary is computed fresh from the
real tables on every call (never cached), so it can never drift from what the
other pillars actually recorded. This preserves the reviewed codebase's best
architectural instinct while putting it on a proper async query base.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_config import get_logger
from ..models import (
    ApprovalRequest,
    ApprovalStatus,
    FabricCapability,
    Operator,
    PostureAssessment,
    UnifiedSecurityEvent,
)

logger = get_logger(__name__)


class AresService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def record_event(
        self,
        *,
        source_module: str,
        threat_category: str | None,
        severity_score: float,
        raw_payload: dict[str, Any],
        approval_request_id: uuid.UUID | None = None,
    ) -> UnifiedSecurityEvent:
        event = UnifiedSecurityEvent(
            event_id=uuid.uuid4(),
            source_module=source_module,
            threat_category=threat_category,
            severity_score=severity_score,
            raw_payload=raw_payload,
            approval_request_id=approval_request_id,
        )
        self._s.add(event)
        await self._s.flush()
        return event

    async def list_events(
        self,
        *,
        source_module: str | None = None,
        threat_category: str | None = None,
        limit: int = 100,
    ) -> list[UnifiedSecurityEvent]:
        stmt = select(UnifiedSecurityEvent).order_by(UnifiedSecurityEvent.recorded_at.desc())
        if source_module:
            stmt = stmt.where(UnifiedSecurityEvent.source_module == source_module)
        if threat_category:
            stmt = stmt.where(UnifiedSecurityEvent.threat_category == threat_category)
        stmt = stmt.limit(limit)
        return list((await self._s.execute(stmt)).scalars().all())

    async def global_matrix_summary(self) -> dict[str, Any]:
        """Executive rollup — every field derived from a live query."""
        # Fabric health: uninitialised if no capabilities seeded; degraded if
        # any capability is not 'active'.
        cap_rows = (await self._s.execute(select(FabricCapability.operational_status))).scalars().all()
        if not cap_rows:
            fabric_status = "UNINITIALIZED"
        elif all(s == "active" for s in cap_rows):
            fabric_status = "OPERATIONAL"
        else:
            fabric_status = "DEGRADED"

        # Compliance coverage: newest posture assessment's overall score, else 0.
        posture = (
            await self._s.execute(
                select(PostureAssessment.overall_score)
                .order_by(PostureAssessment.recorded_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        # Posture score may be stored as a 0-1 fraction or a 0-100 percent;
        # normalise either to a percentage.
        raw = posture or 0.0
        compliance_pct = round(raw * 100, 1) if raw and raw <= 1 else round(raw, 1)

        active_agents = (
            await self._s.execute(
                select(func.count()).select_from(Operator).where(Operator.active.is_(True))
            )
        ).scalar_one()

        # Threats blocked = high-severity events that staged an approval which
        # was approved/denied (i.e. the gate acted on them).
        threats_blocked = (
            await self._s.execute(
                select(func.count())
                .select_from(UnifiedSecurityEvent)
                .join(ApprovalRequest, UnifiedSecurityEvent.approval_request_id == ApprovalRequest.request_id)
                .where(ApprovalRequest.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.DENIED]))
            )
        ).scalar_one()

        pending_high = (
            await self._s.execute(
                select(func.count())
                .select_from(ApprovalRequest)
                .where(ApprovalRequest.status == ApprovalStatus.PENDING)
            )
        ).scalar_one()

        return {
            "fabric_status": fabric_status,
            "compliance_coverage_pct": compliance_pct,
            "active_agent_count": int(active_agents),
            "threats_blocked_count": int(threats_blocked),
            "pending_approvals": int(pending_high),
            "adversarial_defense_status": "ENGAGED" if pending_high == 0 else "ACTION_REQUIRED",
            "derived": True,
        }
