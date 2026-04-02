"""
API endpoints for prompt management.

Provides CRUD operations for prompts including version history and A/B test performance.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies.dependencies import get_db_session
from app.repositories.prompt_repository import PromptRepository
from app.repositories.ab_test_repository import ABTestRepository

router = APIRouter(prefix="/prompts", tags=["prompts"])
log = logging.getLogger(__name__)


# Response models
class PromptResponse(BaseModel):
    """Prompt response model."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    content: str
    prompt_metadata: dict = Field(default_factory=dict)
    is_active: bool
    parent_id: Optional[str] = None
    created_at: str


class PromptSummaryResponse(BaseModel):
    """Summary prompt response without full content."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    is_active: bool
    parent_id: Optional[str] = None
    created_at: str
    content_preview: str = ""  # First 100 chars


class PromptListResponse(BaseModel):
    """Paginated prompt list response."""
    prompts: list[PromptSummaryResponse]
    total: int
    limit: int
    offset: int


class PromptVersionResponse(BaseModel):
    """Prompt version for history."""
    id: str
    name: str
    content_preview: str
    is_active: bool
    created_at: str
    version_index: int


class PromptVersionHistoryResponse(BaseModel):
    """Prompt version history."""
    prompt_id: str
    versions: list[PromptVersionResponse]
    total_versions: int


class PromptDiffResponse(BaseModel):
    """Diff between two prompt versions."""
    prompt_id: str
    from_version: int
    to_version: int
    from_content: str
    to_content: str
    diff_lines: list[dict]  # {type: "add"|"remove"|"unchanged", line: str}


class ABTestPerformanceResponse(BaseModel):
    """A/B test performance for a prompt version."""
    test_id: str
    status: str
    p_value: Optional[float] = None
    effect_size: Optional[float] = None
    is_significant: Optional[bool] = None
    samples_baseline: int
    samples_improvement: int
    created_at: str
    completed_at: Optional[str] = None


class PromptPerformanceResponse(BaseModel):
    """Performance data for a prompt."""
    prompt_id: str
    ab_tests: list[ABTestPerformanceResponse]
    total_tests: int
    win_rate: float  # Percentage of tests where this version won


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    status: Optional[str] = Query(None, description="Filter by status: active, inactive"),
    search: Optional[str] = Query(None, description="Search by name"),
    limit: int = Query(50, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_db_session),
) -> PromptListResponse:
    """
    List all prompts with optional filtering.

    Supports filtering by active status and searching by name.
    """
    log.info(f"Listing prompts: status={status}, search={search}, limit={limit}, offset={offset}")

    repo = PromptRepository(session)

    # Get prompts based on status filter
    if status == "active":
        prompts = await repo.list_active()
    else:
        prompts = await repo.list_all(limit=1000, offset=0)

    # Apply status filter for inactive
    if status == "inactive":
        prompts = [p for p in prompts if not p.is_active]

    # Apply search filter
    if search:
        search_lower = search.lower()
        prompts = [p for p in prompts if search_lower in p.name.lower()]

    total = len(prompts)

    # Apply pagination
    prompts = prompts[offset:offset + limit]

    return PromptListResponse(
        prompts=[
            PromptSummaryResponse(
                id=p.id,
                name=p.name,
                is_active=p.is_active,
                parent_id=p.parent_id,
                created_at=p.created_at.isoformat() if p.created_at else "",
                content_preview=p.content[:100] + "..." if len(p.content) > 100 else p.content,
            )
            for p in prompts
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{prompt_id}", response_model=PromptResponse)
async def get_prompt(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> PromptResponse:
    """
    Get prompt by ID with full content.

    Returns 404 if prompt not found.
    """
    log.info(f"Getting prompt: id={prompt_id}")

    repo = PromptRepository(session)
    prompt = await repo.get_by_id(prompt_id)

    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")

    return PromptResponse(
        id=prompt.id,
        name=prompt.name,
        content=prompt.content,
        prompt_metadata=prompt.prompt_metadata or {},
        is_active=prompt.is_active,
        parent_id=prompt.parent_id,
        created_at=prompt.created_at.isoformat() if prompt.created_at else "",
    )


@router.get("/{prompt_id}/versions", response_model=PromptVersionHistoryResponse)
async def get_prompt_versions(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> PromptVersionHistoryResponse:
    """
    Get version history for a prompt.

    Traces the lineage from root through all children.
    """
    log.info(f"Getting version history for prompt: id={prompt_id}")

    repo = PromptRepository(session)
    prompt = await repo.get_by_id(prompt_id)

    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")

    # Find root prompt (traverse up parent chain)
    root = prompt
    while root.parent_id:
        parent = await repo.get_by_id(root.parent_id)
        if not parent:
            break
        root = parent

    # Collect all versions starting from root
    versions = []
    version_index = 0

    async def collect_versions(p, idx):
        nonlocal version_index
        versions.append(PromptVersionResponse(
            id=p.id,
            name=p.name,
            content_preview=p.content[:100] + "..." if len(p.content) > 100 else p.content,
            is_active=p.is_active,
            created_at=p.created_at.isoformat() if p.created_at else "",
            version_index=idx,
        ))
        children = await repo.get_children(p.id)
        for child in children:
            version_index += 1
            await collect_versions(child, version_index)

    await collect_versions(root, 0)

    return PromptVersionHistoryResponse(
        prompt_id=prompt_id,
        versions=versions,
        total_versions=len(versions),
    )


@router.get("/{prompt_id}/versions/{version}/diff", response_model=PromptDiffResponse)
async def get_prompt_diff(
    prompt_id: str,
    version: int,
    compare_to: int = Query(None, description="Version to compare to (default: previous)"),
    session: AsyncSession = Depends(get_db_session),
) -> PromptDiffResponse:
    """
    Get diff between two prompt versions.

    Compares specified version with previous or specified compare_to version.
    """
    log.info(f"Getting diff for prompt: id={prompt_id}, version={version}, compare_to={compare_to}")

    repo = PromptRepository(session)
    prompt = await repo.get_by_id(prompt_id)

    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")

    # Get all versions to find by index
    # Find root and collect all versions
    root = prompt
    while root.parent_id:
        parent = await repo.get_by_id(root.parent_id)
        if not parent:
            break
        root = parent

    all_versions = []

    async def collect_all(p):
        all_versions.append(p)
        children = await repo.get_children(p.id)
        for child in children:
            await collect_all(child)

    await collect_all(root)

    if version < 0 or version >= len(all_versions):
        raise HTTPException(status_code=400, detail=f"Invalid version index: {version}")

    to_version = compare_to if compare_to is not None else max(0, version - 1)
    if to_version < 0 or to_version >= len(all_versions):
        raise HTTPException(status_code=400, detail=f"Invalid compare_to version index: {to_version}")

    from_prompt = all_versions[to_version]
    to_prompt = all_versions[version]

    # Compute simple line-by-line diff
    from_lines = from_prompt.content.splitlines()
    to_lines = to_prompt.content.splitlines()

    diff_lines = []

    # Simple diff - show removed and added lines
    from_set = set(from_lines)
    to_set = set(to_lines)

    for line in from_lines:
        if line not in to_set:
            diff_lines.append({"type": "remove", "line": line})
        else:
            diff_lines.append({"type": "unchanged", "line": line})

    for line in to_lines:
        if line not in from_set:
            diff_lines.append({"type": "add", "line": line})

    return PromptDiffResponse(
        prompt_id=prompt_id,
        from_version=to_version,
        to_version=version,
        from_content=from_prompt.content,
        to_content=to_prompt.content,
        diff_lines=diff_lines,
    )


@router.get("/{prompt_id}/performance", response_model=PromptPerformanceResponse)
async def get_prompt_performance(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> PromptPerformanceResponse:
    """
    Get A/B test results per version for a prompt.

    Shows all A/B tests that have involved this prompt.
    """
    log.info(f"Getting performance for prompt: id={prompt_id}")

    repo = PromptRepository(session)
    prompt = await repo.get_by_id(prompt_id)

    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")

    # Query A/B tests for this prompt
    ab_repo = ABTestRepository(session)

    from app.models.sql.ab_test_models import ABTest
    stmt = (
        select(ABTest)
        .where(
            ABTest.artifact_type == "prompt",
            ABTest.artifact_id == prompt_id,
        )
        .order_by(ABTest.created_at.desc())
    )
    result = await session.execute(stmt)
    ab_tests = list(result.scalars().all())

    # Convert to response
    tests = []
    wins = 0

    for test in ab_tests:
        is_significant = test.is_significant == 1 if test.is_significant is not None else None
        if is_significant:
            wins += 1

        tests.append(ABTestPerformanceResponse(
            test_id=test.id,
            status=test.status,
            p_value=test.p_value,
            effect_size=test.effect_size,
            is_significant=is_significant,
            samples_baseline=test.samples_baseline,
            samples_improvement=test.samples_improvement,
            created_at=test.created_at.isoformat() if test.created_at else "",
            completed_at=test.completed_at.isoformat() if test.completed_at else None,
        ))

    total_completed = sum(1 for t in ab_tests if t.status == "completed")
    win_rate = (wins / total_completed * 100) if total_completed > 0 else 0.0

    return PromptPerformanceResponse(
        prompt_id=prompt_id,
        ab_tests=tests,
        total_tests=len(ab_tests),
        win_rate=win_rate,
    )
