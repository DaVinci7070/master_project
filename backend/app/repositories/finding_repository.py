import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.analysis_models import AnalysisFinding
from app.models.sql.telemetry_models import ExecutionTelemetry
from app.models.schemas.analysis_schemas import AnalysisFindingCreate

log = logging.getLogger(__name__)


class FindingRepository:
    """
    Repository for AnalysisFinding database operations.

    Findings are append-only artifacts from agent analysis.
    They can be updated only to set priority_rank from Product Owner.

    All operations are async for non-blocking database access.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize repository with database session.

        Args:
            session: SQLAlchemy async session for database operations.
        """
        self.session = session

    async def create(self, data: AnalysisFindingCreate) -> AnalysisFinding:
        """
        Create a new analysis finding.

        Args:
            data: Validated finding data from schema.

        Returns:
            Created AnalysisFinding database model.
        """
        log.info(
            f"Creating finding for execution={data.execution_telemetry_id[:8]}..., "
            f"category={data.category}, severity={data.severity}"
        )

        db_finding = AnalysisFinding(
            execution_telemetry_id=data.execution_telemetry_id,
            category=data.category,
            severity=data.severity,
            evidence=data.evidence,
            suggested_fix=data.suggested_fix,
            priority_rank=data.priority_rank,
            input_content=data.input_content,
            output_content=data.output_content,
        )

        self.session.add(db_finding)
        await self.session.commit()
        await self.session.refresh(db_finding)

        log.info(f"Created finding id={db_finding.id}")
        return db_finding

    async def get_by_id(self, finding_id: str) -> Optional[AnalysisFinding]:
        """
        Get a finding by its ID.

        Args:
            finding_id: UUID of the finding.

        Returns:
            AnalysisFinding or None if not found.
        """
        stmt = select(AnalysisFinding).where(AnalysisFinding.id == finding_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_execution_id(
        self, execution_id: str
    ) -> List[AnalysisFinding]:
        """
        Get all findings for a specific execution.

        Results are ordered by severity (critical first) then created_at.

        Args:
            execution_id: UUID of the execution telemetry record.

        Returns:
            List of AnalysisFinding records.
        """
        stmt = (
            select(AnalysisFinding)
            .where(AnalysisFinding.execution_telemetry_id == execution_id)
            .order_by(
                AnalysisFinding.severity,
                AnalysisFinding.created_at,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_agent_id(
        self, agent_id: str, limit: int = 50
    ) -> List[AnalysisFinding]:
        """
        Get findings for all executions of a specific agent.

        Requires JOIN with ExecutionTelemetry to filter by agent.
        Results are ordered by created_at descending (most recent first).

        Args:
            agent_id: UUID of the agent.
            limit: Maximum number of findings to return.

        Returns:
            List of AnalysisFinding records.
        """
        stmt = (
            select(AnalysisFinding)
            .join(
                ExecutionTelemetry,
                AnalysisFinding.execution_telemetry_id == ExecutionTelemetry.id
            )
            .where(ExecutionTelemetry.agent_id == agent_id)
            .order_by(AnalysisFinding.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_priority(
        self, finding_id: str, priority_rank: int
    ) -> Optional[AnalysisFinding]:
        """
        Update the priority rank of a finding.

        Called by Product Owner agent after prioritization.

        Args:
            finding_id: UUID of the finding to update.
            priority_rank: New priority rank (1 = highest priority).

        Returns:
            Updated AnalysisFinding or None if not found.
        """
        log.info(f"Updating priority for finding={finding_id}, rank={priority_rank}")

        finding = await self.get_by_id(finding_id)
        if not finding:
            log.warning(f"Finding not found: {finding_id}")
            return None

        finding.priority_rank = priority_rank
        await self.session.commit()
        await self.session.refresh(finding)

        log.info(f"Updated finding priority: id={finding_id}, rank={priority_rank}")
        return finding

    async def get_recent_by_category(
        self, category: str, limit: int = 10
    ) -> List[AnalysisFinding]:
        """
        Get recent findings of a specific category.

        Used for pattern detection: identify recurring issues
        of the same type across different executions.

        Args:
            category: Finding category (prompt, topology, skill, error).
            limit: Maximum number of findings to return.

        Returns:
            List of AnalysisFinding records, most recent first.
        """
        stmt = (
            select(AnalysisFinding)
            .where(AnalysisFinding.category == category)
            .order_by(AnalysisFinding.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
