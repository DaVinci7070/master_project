"""
API endpoints for Gap Plan monitoring and management.

Provides endpoints for viewing gap plan progress, history, and retry operations.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.dependencies import get_db_session, AsyncSessionLocal
from app.orchestration.execution.gap_plan import GapPlanService
from app.models.sql.gap_plan_models import GapPlanStatus, GapStatus

router = APIRouter(prefix="/gap-plans", tags=["gap-plans"])
log = logging.getLogger(__name__)


# ============================================================================
# Response Models
# ============================================================================

class GapProgressResponse(BaseModel):
    """Progress summary for a gap plan."""
    total: int
    completed: int
    failed: int
    pending: int
    percentage: float


class GapItemResponse(BaseModel):
    """Single gap item in a plan."""
    id: str
    gap_type: str
    affected_capability: str
    severity: str
    description: Optional[str] = None
    status: str
    artifact_id: Optional[str] = None
    artifact_type: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class GapPlanResponse(BaseModel):
    """Full gap plan response."""
    id: str
    challenge_id: str
    execution_id: Optional[str] = None
    cycle_number: int
    status: str
    progress: GapProgressResponse
    gaps: List[GapItemResponse]
    initial_confidence: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None


class GapPlanSummaryResponse(BaseModel):
    """Summary of a gap plan for listing."""
    id: str
    cycle_number: int
    status: str
    total_gaps: int
    completed_gaps: int
    failed_gaps: int
    created_at: str
    completed_at: Optional[str] = None


class GapPlanHistoryResponse(BaseModel):
    """History of all gap plans for a challenge."""
    challenge_id: str
    total_cycles: int
    plans: List[GapPlanSummaryResponse]


class RetryGapRequest(BaseModel):
    """Request to retry a failed gap."""
    force: bool = Field(default=False, description="Force retry even if already completed")


class RetryGapResponse(BaseModel):
    """Response after retrying a gap."""
    gap_id: str
    status: str
    message: str


# ============================================================================
# Helper Functions
# ============================================================================

def _plan_to_response(plan) -> GapPlanResponse:
    """Convert a CapabilityGapPlan to GapPlanResponse."""
    gaps = plan.gaps or []

    # Calculate progress
    completed = sum(1 for g in gaps if g.get("status") == GapStatus.COMPLETED.value)
    failed = sum(1 for g in gaps if g.get("status") == GapStatus.FAILED.value)
    pending = len(gaps) - completed - failed
    percentage = (completed / len(gaps) * 100) if gaps else 0

    progress = GapProgressResponse(
        total=len(gaps),
        completed=completed,
        failed=failed,
        pending=pending,
        percentage=round(percentage, 1)
    )

    # Convert gaps to response format
    gap_items = [
        GapItemResponse(
            id=g.get("id", ""),
            gap_type=g.get("gap_type", "unknown"),
            affected_capability=g.get("affected_capability", ""),
            severity=g.get("severity", "minor"),
            description=g.get("description"),
            status=g.get("status", "pending"),
            artifact_id=g.get("artifact_id"),
            artifact_type=g.get("artifact_type"),
            error_message=g.get("error_message"),
            started_at=g.get("started_at"),
            completed_at=g.get("completed_at"),
        )
        for g in gaps
    ]

    return GapPlanResponse(
        id=plan.id,
        challenge_id=plan.challenge_id,
        execution_id=plan.execution_id,
        cycle_number=plan.cycle_number,
        status=plan.status,
        progress=progress,
        gaps=gap_items,
        initial_confidence=plan.initial_confidence,
        created_at=plan.created_at.isoformat() if plan.created_at else "",
        updated_at=plan.updated_at.isoformat() if plan.updated_at else None,
        completed_at=plan.completed_at.isoformat() if plan.completed_at else None,
    )


def _plan_to_summary(plan) -> GapPlanSummaryResponse:
    """Convert a CapabilityGapPlan to summary response."""
    return GapPlanSummaryResponse(
        id=plan.id,
        cycle_number=plan.cycle_number,
        status=plan.status,
        total_gaps=plan.total_gaps,
        completed_gaps=plan.completed_gaps,
        failed_gaps=plan.failed_gaps,
        created_at=plan.created_at.isoformat() if plan.created_at else "",
        completed_at=plan.completed_at.isoformat() if plan.completed_at else None,
    )


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/{plan_id}", response_model=GapPlanResponse)
async def get_gap_plan(
    plan_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> GapPlanResponse:
    """
    Get a specific gap plan by ID.

    Returns full plan details including all gaps and their status.
    """
    log.info(f"Getting gap plan: {plan_id}")

    service = GapPlanService(AsyncSessionLocal)
    plan = await service.get_plan(plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail=f"Gap plan not found: {plan_id}")

    return _plan_to_response(plan)


@router.get("/challenge/{challenge_id}/current", response_model=GapPlanResponse)
async def get_current_gap_plan(
    challenge_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> GapPlanResponse:
    """
    Get the current (active or most recent) gap plan for a challenge.

    Returns the most relevant plan:
    - Active plan if one exists (pending or in_progress)
    - Otherwise the most recent completed/failed plan
    """
    log.info(f"Getting current gap plan for challenge: {challenge_id}")

    service = GapPlanService(AsyncSessionLocal)

    # Try to get active plan first
    plan = await service.get_active_plan(challenge_id)

    if not plan:
        # Fall back to latest plan
        plan = await service.get_latest_plan(challenge_id)

    if not plan:
        raise HTTPException(
            status_code=404,
            detail=f"No gap plan found for challenge: {challenge_id}"
        )

    return _plan_to_response(plan)


@router.get("/challenge/{challenge_id}/history", response_model=GapPlanHistoryResponse)
async def get_gap_plan_history(
    challenge_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> GapPlanHistoryResponse:
    """
    Get all gap plans (all cycles) for a challenge.

    Returns a summary of each cycle's plan.
    """
    log.info(f"Getting gap plan history for challenge: {challenge_id}")

    service = GapPlanService(AsyncSessionLocal)
    plans = await service.get_plan_history(challenge_id)

    return GapPlanHistoryResponse(
        challenge_id=challenge_id,
        total_cycles=len(plans),
        plans=[_plan_to_summary(p) for p in plans]
    )


@router.post("/{plan_id}/retry-gap/{gap_id}", response_model=RetryGapResponse)
async def retry_gap(
    plan_id: str,
    gap_id: str,
    request: RetryGapRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> RetryGapResponse:
    """
    Retry building a specific gap.

    Only works for failed gaps unless force=true.
    The rebuild happens asynchronously in the background.
    """
    log.info(f"Retrying gap: plan_id={plan_id}, gap_id={gap_id}, force={request.force}")

    service = GapPlanService(AsyncSessionLocal)
    plan = await service.get_plan(plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail=f"Gap plan not found: {plan_id}")

    # Find the gap
    target_gap = None
    for gap in (plan.gaps or []):
        if gap.get("id") == gap_id:
            target_gap = gap
            break

    if not target_gap:
        raise HTTPException(status_code=404, detail=f"Gap not found: {gap_id}")

    current_status = target_gap.get("status", "pending")

    # Check if retry is allowed
    if current_status == GapStatus.COMPLETED.value and not request.force:
        raise HTTPException(
            status_code=400,
            detail="Gap already completed. Use force=true to retry anyway."
        )

    if current_status == GapStatus.BUILDING.value:
        raise HTTPException(
            status_code=400,
            detail="Gap is currently being built. Please wait."
        )

    # Reset gap to pending for retry
    await service.update_gap_status(
        plan_id=plan_id,
        gap_id=gap_id,
        status=GapStatus.PENDING.value,
        artifact_id=None,
        artifact_type=None,
        error_message=None
    )

    # Trigger rebuild in background
    background_tasks.add_task(
        _rebuild_single_gap,
        plan_id=plan_id,
        gap_id=gap_id,
        gap_dict=target_gap,
    )

    return RetryGapResponse(
        gap_id=gap_id,
        status="retry_queued",
        message=f"Gap '{target_gap.get('affected_capability')}' queued for rebuild"
    )


async def _rebuild_single_gap(
    plan_id: str,
    gap_id: str,
    gap_dict: dict,
) -> None:
    """
    Background task to rebuild a single gap.
    """
    from app.dependencies.dependencies import AsyncSessionLocal
    from app.orchestration.execution.gap_plan import GapPlanService
    from app.orchestration.intervention.capability_builder import CapabilityBuilder
    from app.orchestration.intervention.injector import CapabilityInjector
    from app.orchestration.topology.loader import TopologyLoader
    from app.orchestration.agents.developer_team import DeveloperTeamOrchestrator
    from app.orchestration.agents.spawner import AgentSpawnerService
    from app.orchestration.agents.registry import RuntimeAgentRegistry
    from app.feedback_loop.improvement.prompt_improver import AgentPromptImprover
    from app.core.llm_client import LLMClient
    from app.models.schemas.analysis_schemas import CapabilityGap, GapType, GapSeverity

    log.info(f"Rebuilding gap: plan_id={plan_id}, gap_id={gap_id}")

    async with AsyncSessionLocal() as session:
        try:
            service = GapPlanService(AsyncSessionLocal)

            # Mark as building
            await service.update_gap_status(
                plan_id=plan_id,
                gap_id=gap_id,
                status=GapStatus.BUILDING.value
            )

            # Get plan to access challenge info
            plan = await service.get_plan(plan_id)
            if not plan:
                log.error(f"Plan not found during rebuild: {plan_id}")
                return

            # Get challenge text from initial assessment
            challenge_text = ""
            if plan.initial_assessment:
                challenge_text = plan.initial_assessment.get("challenge_text", "")

            # Create builder dependencies
            llm_client = LLMClient()
            registry = RuntimeAgentRegistry(max_concurrent_agents=5)
            spawner = AgentSpawnerService(registry, llm_client)
            developer_team = DeveloperTeamOrchestrator(
                spawner=spawner,
                llm_client=llm_client,
                registry=registry
            )

            gap_type = gap_dict.get("gap_type", "missing_skill")
            affected_capability = gap_dict.get("affected_capability", "")
            description = gap_dict.get("description", "")
            severity = gap_dict.get("severity", "important")

            # Route to appropriate builder
            if gap_type == "weak_prompt":
                # Use prompt improver
                async def llm_wrapper(messages):
                    return await llm_client.chat(messages)

                improver = AgentPromptImprover(AsyncSessionLocal, llm_fn=llm_wrapper)
                result = await improver.improve(
                    affected_capability=affected_capability,
                    gap_description=description,
                    challenge_context=challenge_text
                )
            else:
                # Use capability builder
                builder = CapabilityBuilder(developer_team, AsyncSessionLocal)

                gap = CapabilityGap(
                    gap_type=GapType(gap_type) if gap_type in [e.value for e in GapType] else GapType.MISSING_SKILL,
                    affected_capability=affected_capability,
                    severity=GapSeverity(severity) if severity in [e.value for e in GapSeverity] else GapSeverity.IMPORTANT,
                    description=description
                )

                result = await builder.build_for_gap(
                    gap=gap,
                    challenge_text=challenge_text,
                    attempt_number=1,
                    previous_failures=[]
                )

            if result.success and result.artifact_id:
                # Inject capability
                topology_loader = TopologyLoader(AsyncSessionLocal)
                await topology_loader.load()
                injector = CapabilityInjector(topology_loader, AsyncSessionLocal)

                inject_success, inject_msg = await injector.inject(
                    artifact_type=result.artifact_type,
                    artifact_id=result.artifact_id
                )

                if inject_success:
                    await service.update_gap_status(
                        plan_id=plan_id,
                        gap_id=gap_id,
                        status=GapStatus.COMPLETED.value,
                        artifact_id=result.artifact_id,
                        artifact_type=result.artifact_type
                    )
                    log.info(f"Gap rebuild successful: {gap_id}")
                else:
                    await service.update_gap_status(
                        plan_id=plan_id,
                        gap_id=gap_id,
                        status=GapStatus.FAILED.value,
                        error_message=f"Injection failed: {inject_msg}"
                    )
                    log.warning(f"Gap injection failed: {gap_id} - {inject_msg}")
            else:
                await service.update_gap_status(
                    plan_id=plan_id,
                    gap_id=gap_id,
                    status=GapStatus.FAILED.value,
                    error_message=result.failure_reason
                )
                log.warning(f"Gap rebuild failed: {gap_id} - {result.failure_reason}")

        except Exception as e:
            log.error(f"Gap rebuild error: {gap_id} - {e}")

            try:
                await service.update_gap_status(
                    plan_id=plan_id,
                    gap_id=gap_id,
                    status=GapStatus.FAILED.value,
                    error_message=str(e)
                )
            except Exception:
                pass


# ============================================================================
# Challenge-scoped Endpoints (aliases for convenience)
# ============================================================================

@router.get("/by-challenge/{challenge_id}", response_model=GapPlanResponse)
async def get_gap_plan_by_challenge(
    challenge_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> GapPlanResponse:
    """
    Alias for /challenge/{challenge_id}/current.

    Get the current gap plan for a challenge.
    """
    return await get_current_gap_plan(challenge_id, session)
