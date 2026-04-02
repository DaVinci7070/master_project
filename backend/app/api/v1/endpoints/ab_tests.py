"""
API endpoints for A/B test management.

Provides access to A/B tests, their status, and results.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.dependencies.dependencies import get_db_session
from app.repositories.ab_test_repository import ABTestRepository
from app.models.sql.ab_test_models import ABTest, ABTestSample

router = APIRouter(prefix="/ab-tests", tags=["ab-tests"])
log = logging.getLogger(__name__)


# Response models
class ABTestSampleResponse(BaseModel):
    """A/B test sample response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    test_id: str
    execution_id: str
    variant: str
    quality_score: float
    latency_ms: float
    is_error: int
    composite_score: float
    created_at: str


class ABTestSummaryResponse(BaseModel):
    """Summary of an A/B test."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_type: str
    artifact_id: str
    status: str
    samples_baseline: int
    samples_improvement: int
    is_significant: Optional[bool] = None
    created_at: str
    completed_at: Optional[str] = None


class ABTestDetailResponse(BaseModel):
    """Detailed A/B test response with samples and results."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    improvement_attempt_id: str
    artifact_type: str
    artifact_id: str
    version_baseline: int
    version_improvement: int
    metric_weights: dict = Field(default_factory=dict)
    status: str
    samples_baseline: int
    samples_improvement: int
    p_value: Optional[float] = None
    effect_size: Optional[float] = None
    is_significant: Optional[bool] = None
    confidence_interval_low: Optional[float] = None
    confidence_interval_high: Optional[float] = None
    baseline_mean: Optional[float] = None
    improvement_mean: Optional[float] = None
    created_at: str
    completed_at: Optional[str] = None
    samples: list[ABTestSampleResponse] = Field(default_factory=list)


class ABTestListResponse(BaseModel):
    """Paginated A/B test list response."""
    tests: list[ABTestSummaryResponse]
    total: int
    limit: int
    offset: int


class ActiveTestsResponse(BaseModel):
    """Currently running A/B tests."""
    tests: list[ABTestSummaryResponse]
    total: int


@router.get("", response_model=ABTestListResponse)
async def list_ab_tests(
    status: Optional[str] = Query(None, description="Filter by status: pending, running, completed, cancelled"),
    artifact_type: Optional[str] = Query(None, description="Filter by artifact type: prompt, agent, skill"),
    limit: int = Query(50, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_db_session),
) -> ABTestListResponse:
    """
    List A/B tests with status filtering.

    Supports filtering by status and artifact type.
    """
    log.info(f"Listing A/B tests: status={status}, artifact_type={artifact_type}, limit={limit}, offset={offset}")

    # Build query
    stmt = select(ABTest).order_by(ABTest.created_at.desc())

    if status:
        stmt = stmt.where(ABTest.status == status)

    if artifact_type:
        stmt = stmt.where(ABTest.artifact_type == artifact_type)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply pagination
    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    tests = list(result.scalars().all())

    return ABTestListResponse(
        tests=[
            ABTestSummaryResponse(
                id=t.id,
                artifact_type=t.artifact_type,
                artifact_id=t.artifact_id,
                status=t.status,
                samples_baseline=t.samples_baseline,
                samples_improvement=t.samples_improvement,
                is_significant=t.is_significant == 1 if t.is_significant is not None else None,
                created_at=t.created_at.isoformat() if t.created_at else "",
                completed_at=t.completed_at.isoformat() if t.completed_at else None,
            )
            for t in tests
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/active", response_model=ActiveTestsResponse)
async def get_active_tests(
    session: AsyncSession = Depends(get_db_session),
) -> ActiveTestsResponse:
    """
    Get currently running A/B tests.

    Returns tests with status "pending" or "running".
    """
    log.info("Getting active A/B tests")

    repo = ABTestRepository(session)
    tests = await repo.get_active_tests()

    return ActiveTestsResponse(
        tests=[
            ABTestSummaryResponse(
                id=t.id,
                artifact_type=t.artifact_type,
                artifact_id=t.artifact_id,
                status=t.status,
                samples_baseline=t.samples_baseline,
                samples_improvement=t.samples_improvement,
                is_significant=None,  # Active tests don't have results yet
                created_at=t.created_at.isoformat() if t.created_at else "",
                completed_at=None,
            )
            for t in tests
        ],
        total=len(tests),
    )


@router.get("/{test_id}", response_model=ABTestDetailResponse)
async def get_ab_test(
    test_id: str,
    include_samples: bool = Query(True, description="Include individual samples"),
    session: AsyncSession = Depends(get_db_session),
) -> ABTestDetailResponse:
    """
    Get A/B test detail with samples and results.

    Returns 404 if test not found.
    """
    log.info(f"Getting A/B test: id={test_id}, include_samples={include_samples}")

    repo = ABTestRepository(session)
    test = await repo.get_test(test_id)

    if not test:
        raise HTTPException(status_code=404, detail=f"A/B test not found: {test_id}")

    # Get samples if requested
    samples = []
    if include_samples:
        sample_records = await repo.get_samples(test_id)
        samples = [
            ABTestSampleResponse(
                id=s.id,
                test_id=s.test_id,
                execution_id=s.execution_id,
                variant=s.variant,
                quality_score=s.quality_score,
                latency_ms=s.latency_ms,
                is_error=s.is_error,
                composite_score=s.composite_score,
                created_at=s.created_at.isoformat() if s.created_at else "",
            )
            for s in sample_records
        ]

    return ABTestDetailResponse(
        id=test.id,
        improvement_attempt_id=test.improvement_attempt_id,
        artifact_type=test.artifact_type,
        artifact_id=test.artifact_id,
        version_baseline=test.version_baseline,
        version_improvement=test.version_improvement,
        metric_weights=test.metric_weights or {},
        status=test.status,
        samples_baseline=test.samples_baseline,
        samples_improvement=test.samples_improvement,
        p_value=test.p_value,
        effect_size=test.effect_size,
        is_significant=test.is_significant == 1 if test.is_significant is not None else None,
        confidence_interval_low=test.confidence_interval_low,
        confidence_interval_high=test.confidence_interval_high,
        baseline_mean=getattr(test, 'baseline_mean', None),
        improvement_mean=getattr(test, 'improvement_mean', None),
        created_at=test.created_at.isoformat() if test.created_at else "",
        completed_at=test.completed_at.isoformat() if test.completed_at else None,
        samples=samples,
    )
