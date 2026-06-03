import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.dependencies import get_db_session
from app.repositories.skill_repository import SkillRepository
from app.core.config import settings

router = APIRouter(prefix="/skills", tags=["skills"])
log = logging.getLogger(__name__)


class TestCaseResponse(BaseModel):
    """Test case response model."""
    name: str
    test_type: str
    input_data: dict = Field(default_factory=dict)
    expected_output: Optional[dict] = None


class SkillResponse(BaseModel):
    """Skill response model."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    code: str
    test_cases: list[dict] = Field(default_factory=list)
    skill_metadata: dict = Field(default_factory=dict)
    is_active: bool
    parent_id: Optional[str] = None
    created_at: str


class SkillSummaryResponse(BaseModel):
    """Summary skill response without full code."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    skill_type: str = "functional"
    is_active: bool
    test_count: int = 0
    parent_id: Optional[str] = None
    created_at: str
    health_status: str = "unknown"


class SkillDetailResponse(BaseModel):
    """Detailed skill response with code and test results."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    skill_type: str = "functional"
    applicability: Optional[str] = None
    instructions: Optional[str] = None
    termination: Optional[str] = None
    interface: Optional[dict] = None
    code: Optional[str] = None
    test_cases: list[dict] = Field(default_factory=list)
    skill_metadata: dict = Field(default_factory=dict)
    is_active: bool
    parent_id: Optional[str] = None
    created_at: str
    health_status: str = "unknown"
    version_count: int = 0


class SkillListResponse(BaseModel):
    """Paginated skill list response."""
    skills: list[SkillSummaryResponse]
    total: int
    limit: int
    offset: int


class TestExecutionResponse(BaseModel):
    """Test execution history response."""
    test_name: str
    test_type: str
    passed: bool
    execution_time_ms: float
    executed_at: str
    error_message: Optional[str] = None


class TestHistoryResponse(BaseModel):
    """Test execution history for a skill."""
    skill_id: str
    executions: list[TestExecutionResponse]
    total_runs: int
    pass_rate: float


class SkillBuildAttemptSummary(BaseModel):
    """SkillBuildAttempt summary — one build iteration for a skill version."""
    id: str
    attempt_number: int
    capability: str
    approach: Optional[str] = None
    success: bool
    error_type: Optional[str] = None
    error_type_classified: Optional[str] = None
    lesson_learned: Optional[str] = None
    failure_analysis: Optional[dict] = None
    code_snapshot: Optional[str] = None
    created_at: str


class SkillVersionEntry(BaseModel):
    """One skill version in a lineage chain."""
    id: str
    name: str
    version_index: int
    parent_id: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    created_at: str
    build_attempts: list[SkillBuildAttemptSummary] = Field(default_factory=list)


class SkillVersionHistoryResponse(BaseModel):
    """Full lineage (root → requested) + build attempts per version.

    Used by the Evolution-API (Sprint 2 / F6) so the frontend can show
    skill evolution with lessons_learned and code-snapshot diffs.
    """
    skill_id: str
    total_versions: int
    lineage: list[SkillVersionEntry]


def _compute_health_status(skill) -> str:
    """Compute health status from skill metadata."""
    metadata = skill.skill_metadata or {}

    last_test_result = metadata.get("last_test_result")
    if last_test_result:
        if last_test_result.get("all_passed", False):
            return "healthy"
        else:
            return "failing"

    if not skill.test_cases or len(skill.test_cases) == 0:
        return "unknown"

    return "unknown"


@router.get("", response_model=SkillListResponse)
async def list_skills(
    status: Optional[str] = Query(None, description="Filter by status: active, inactive, healthy, failing"),
    search: Optional[str] = Query(None, description="Search by name or description"),
    limit: int = Query(50, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_db_session),
) -> SkillListResponse:
    """
    List all skills with health status.

    Supports filtering by active status and health status.
    """
    log.info(f"Listing skills: status={status}, search={search}, limit={limit}, offset={offset}")

    repo = SkillRepository(session)

    if status == "active":
        skills = await repo.list_active()
    else:
        skills = await repo.list_all(limit=1000, offset=0)

    if status == "inactive":
        skills = [s for s in skills if not s.is_active]
    elif status == "healthy":
        skills = [s for s in skills if _compute_health_status(s) == "healthy"]
    elif status == "failing":
        skills = [s for s in skills if _compute_health_status(s) == "failing"]

    if search:
        search_lower = search.lower()
        skills = [
            s for s in skills
            if search_lower in s.name.lower() or
               (s.description and search_lower in s.description.lower())
        ]

    total = len(skills)

    skills = skills[offset:offset + limit]

    return SkillListResponse(
        skills=[
            SkillSummaryResponse(
                id=s.id,
                name=s.name,
                description=s.description,
                skill_type=s.skill_type or "functional",
                is_active=s.is_active,
                test_count=len(s.test_cases or []),
                parent_id=s.parent_id,
                created_at=s.created_at.isoformat() if s.created_at else "",
                health_status=_compute_health_status(s),
            )
            for s in skills
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{skill_id}", response_model=SkillDetailResponse)
async def get_skill(
    skill_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> SkillDetailResponse:
    """
    Get skill by ID with code and test results.

    Returns 404 if skill not found.
    """
    log.info(f"Getting skill: id={skill_id}")

    repo = SkillRepository(session)
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")

    children = await repo.get_children(skill_id)
    version_count = len(children) + 1

    return SkillDetailResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        skill_type=skill.skill_type or "functional",
        applicability=skill.applicability,
        instructions=skill.instructions,
        termination=skill.termination,
        interface=skill.interface,
        code=skill.code,
        test_cases=skill.test_cases or [],
        skill_metadata=skill.skill_metadata or {},
        is_active=skill.is_active,
        parent_id=skill.parent_id,
        created_at=skill.created_at.isoformat() if skill.created_at else "",
        health_status=_compute_health_status(skill),
        version_count=version_count,
    )


@router.get("/{skill_id}/tests", response_model=TestHistoryResponse)
async def get_skill_tests(
    skill_id: str,
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    session: AsyncSession = Depends(get_db_session),
) -> TestHistoryResponse:
    """
    Get test execution history for a skill.

    Returns test runs with pass/fail status.
    """
    log.info(f"Getting test history for skill: id={skill_id}")

    repo = SkillRepository(session)
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")

    metadata = skill.skill_metadata or {}
    test_history = metadata.get("test_history", [])

    executions = []
    for entry in test_history[:limit]:
        executions.append(TestExecutionResponse(
            test_name=entry.get("test_name", "unknown"),
            test_type=entry.get("test_type", "unknown"),
            passed=entry.get("passed", False),
            execution_time_ms=entry.get("execution_time_ms", 0.0),
            executed_at=entry.get("executed_at", ""),
            error_message=entry.get("error_message"),
        ))

    total_runs = len(test_history)
    passed_runs = sum(1 for e in test_history if e.get("passed", False))
    pass_rate = (passed_runs / total_runs * 100) if total_runs > 0 else 0.0

    return TestHistoryResponse(
        skill_id=skill_id,
        executions=executions,
        total_runs=total_runs,
        pass_rate=pass_rate,
    )


@router.get("/{skill_id}/version-history", response_model=SkillVersionHistoryResponse)
async def get_skill_version_history(
    skill_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> SkillVersionHistoryResponse:
    """
    Get full version lineage for a skill, root → requested.

    For each version in the chain, returns associated SkillBuildAttempts
    (lesson_learned, failure_analysis, code snapshots) so callers can
    render skill evolution with full build context.

    Returns 404 if the skill does not exist.
    """
    from sqlalchemy import select
    from app.models.sql.skill_build_models import SkillBuildAttempt

    log.info(f"Getting version-history for skill: id={skill_id}")

    repo = SkillRepository(session)
    skill = await repo.get_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")

    chain: list = [skill]
    seen: set[str] = {skill.id}
    current = skill
    while current.parent_id and current.parent_id not in seen:
        parent = await repo.get_by_id(current.parent_id)
        if parent is None:
            break
        chain.append(parent)
        seen.add(parent.id)
        current = parent

    chain.reverse()

    skill_ids = [s.id for s in chain]
    attempts_stmt = (
        select(SkillBuildAttempt)
        .where(SkillBuildAttempt.skill_id.in_(skill_ids))
        .order_by(SkillBuildAttempt.attempt_number.asc())
    )
    attempts_result = await session.execute(attempts_stmt)
    attempts = list(attempts_result.scalars().all())

    attempts_by_skill: dict[str, list] = {sid: [] for sid in skill_ids}
    for a in attempts:
        if a.skill_id in attempts_by_skill:
            attempts_by_skill[a.skill_id].append(a)

    lineage: list[SkillVersionEntry] = []
    for index, s in enumerate(chain, start=1):
        attempt_summaries = [
            SkillBuildAttemptSummary(
                id=a.id,
                attempt_number=a.attempt_number,
                capability=a.capability,
                approach=a.approach,
                success=a.success,
                error_type=a.error_type,
                error_type_classified=a.error_type_classified,
                lesson_learned=a.lesson_learned,
                failure_analysis=a.failure_analysis,
                code_snapshot=a.code_snapshot,
                created_at=a.created_at.isoformat() if a.created_at else "",
            )
            for a in attempts_by_skill.get(s.id, [])
        ]
        lineage.append(SkillVersionEntry(
            id=s.id,
            name=s.name,
            version_index=index,
            parent_id=s.parent_id,
            description=s.description,
            is_active=s.is_active,
            created_at=s.created_at.isoformat() if s.created_at else "",
            build_attempts=attempt_summaries,
        ))

    return SkillVersionHistoryResponse(
        skill_id=skill_id,
        total_versions=len(lineage),
        lineage=lineage,
    )


class SkillUpdateRequest(BaseModel):
    """Request model for updating a skill."""
    name: Optional[str] = None
    description: Optional[str] = None
    skill_type: Optional[str] = None
    applicability: Optional[str] = None
    instructions: Optional[str] = None
    termination: Optional[str] = None
    interface: Optional[dict] = None
    is_active: Optional[bool] = None


@router.patch("/{skill_id}", response_model=SkillDetailResponse)
async def update_skill(
    skill_id: str,
    update: SkillUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SkillDetailResponse:
    """Update a skill's fields. Planning skills support editing instructions, applicability, termination."""
    repo = SkillRepository(session)

    update_data = update.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    skill = await repo.update(skill_id, update_data)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")

    await session.commit()

    children = await repo.get_children(skill_id)
    version_count = len(children) + 1

    return SkillDetailResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        skill_type=skill.skill_type or "functional",
        applicability=skill.applicability,
        instructions=skill.instructions,
        termination=skill.termination,
        interface=skill.interface,
        code=skill.code,
        test_cases=skill.test_cases or [],
        skill_metadata=skill.skill_metadata or {},
        is_active=skill.is_active,
        parent_id=skill.parent_id,
        created_at=skill.created_at.isoformat() if skill.created_at else "",
        health_status=_compute_health_status(skill),
        version_count=version_count,
    )


class RegistrySkillStats(BaseModel):
    """Stats for a single loaded skill."""
    id: str
    name: str
    executions: int
    success_rate: float
    avg_execution_ms: float
    last_executed: Optional[str] = None


class RegistryStatsResponse(BaseModel):
    """Skill registry statistics response."""
    enabled: bool
    initialized: bool = False
    total_skills: int = 0
    capabilities_indexed: int = 0
    total_executions: int = 0
    skills: list[RegistrySkillStats] = Field(default_factory=list)


@router.get("/registry/stats", response_model=RegistryStatsResponse)
async def get_registry_stats() -> RegistryStatsResponse:
    """
    Get skill registry statistics.

    Returns information about hot-loaded skills and their execution stats.
    Only available when hot_reload_enabled is True.
    """
    if not settings.hot_reload_enabled:
        return RegistryStatsResponse(
            enabled=False,
            initialized=False,
            total_skills=0,
            capabilities_indexed=0,
            total_executions=0,
            skills=[],
        )

    from app.skills.runtime.registry import SkillRegistry

    registry = SkillRegistry.get_instance()
    stats = registry.stats()

    return RegistryStatsResponse(
        enabled=True,
        initialized=stats.get("initialized", False),
        total_skills=stats.get("total_skills", 0),
        capabilities_indexed=stats.get("capabilities_indexed", 0),
        total_executions=stats.get("total_executions", 0),
        skills=[
            RegistrySkillStats(
                id=s["id"],
                name=s["name"],
                executions=s["executions"],
                success_rate=s["success_rate"],
                avg_execution_ms=s["avg_execution_ms"],
                last_executed=s.get("last_executed"),
            )
            for s in stats.get("skills", [])
        ],
    )
