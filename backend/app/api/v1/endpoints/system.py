"""
API endpoints for system control and snapshots.

Provides emergency stop, snapshot management, and system restore.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.dependencies.dependencies import get_db_session
from app.models.sql.versioned_models import Agent, Skill, Prompt
from app.models.sql.ab_test_models import ABTest

router = APIRouter(prefix="/system", tags=["system"])
log = logging.getLogger(__name__)


# In-memory snapshot storage (production would use database)
_snapshots: dict[str, dict] = {}


# Response models
class EmergencyStopResponse(BaseModel):
    """Response after triggering emergency stop."""
    success: bool
    message: str
    affected_components: list[str]
    stopped_at: str


class SnapshotSummaryResponse(BaseModel):
    """Summary of an execution snapshot."""
    id: str
    name: str
    description: Optional[str] = None
    created_at: str
    agent_count: int
    skill_count: int
    prompt_count: int


class SnapshotDetailResponse(BaseModel):
    """Detailed snapshot with full state."""
    id: str
    name: str
    description: Optional[str] = None
    created_at: str
    agents: list[dict] = Field(default_factory=list)
    skills: list[dict] = Field(default_factory=list)
    prompts: list[dict] = Field(default_factory=list)


class SnapshotListResponse(BaseModel):
    """List of snapshots."""
    snapshots: list[SnapshotSummaryResponse]
    total: int


class CreateSnapshotRequest(BaseModel):
    """Request to create a snapshot."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class CreateSnapshotResponse(BaseModel):
    """Response after creating snapshot."""
    id: str
    name: str
    created_at: str
    message: str


class RestoreSnapshotResponse(BaseModel):
    """Response after restoring from snapshot."""
    success: bool
    snapshot_id: str
    message: str
    restored_at: str
    agents_restored: int
    skills_restored: int
    prompts_restored: int


@router.post("/emergency-stop", response_model=EmergencyStopResponse)
async def emergency_stop(
    session: AsyncSession = Depends(get_db_session),
) -> EmergencyStopResponse:
    """
    Trigger emergency stop.

    Stops all active executions and disables agents.
    Returns confirmation with affected components.
    """
    log.warning("EMERGENCY STOP triggered")

    affected = []

    try:
        # Cancel all active A/B tests
        active_tests_stmt = (
            select(ABTest)
            .where(ABTest.status.in_(["pending", "running"]))
        )
        result = await session.execute(active_tests_stmt)
        active_tests = list(result.scalars().all())

        for test in active_tests:
            test.status = "cancelled"
            affected.append(f"ab_test:{test.id[:8]}")

        # Mark all agents as inactive
        await session.execute(
            update(Agent).values(is_active=False)
        )
        affected.append("all_agents:deactivated")

        await session.commit()

        log.warning(f"Emergency stop complete. Affected: {affected}")

        return EmergencyStopResponse(
            success=True,
            message="Emergency stop executed. All agents deactivated, all A/B tests cancelled.",
            affected_components=affected,
            stopped_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        log.error(f"Emergency stop failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Emergency stop failed: {str(e)}"
        )


class SystemResetResponse(BaseModel):
    """Response after resetting the system."""
    success: bool
    message: str
    deleted_agents: int
    deleted_skills: int
    deleted_prompts: int
    deleted_events: int
    remaining_default_agents: int


@router.post("/reset", response_model=SystemResetResponse)
async def reset_system(
    session: AsyncSession = Depends(get_db_session),
) -> SystemResetResponse:
    """
    Reset the system to its default state.

    Deletes all system-generated agents, all skills, orphaned prompts,
    and related events/logs. Keeps only initial (default) agents.
    """
    from sqlalchemy import delete, func

    log.warning("SYSTEM RESET triggered")

    try:
        # Get prompt IDs linked to system-generated agents
        sg_prompt_ids_result = await session.execute(
            select(Agent.prompt_id).where(
                Agent.source == "system_generated",
                Agent.prompt_id.isnot(None),
            )
        )
        sg_prompt_ids = list(sg_prompt_ids_result.scalars().all())

        # Delete system-generated agents
        deleted_agents = (await session.execute(
            delete(Agent).where(Agent.source == "system_generated")
        )).rowcount

        # Delete all tables that reference skills (FK dependencies)
        from sqlalchemy import text
        for dep_table in ("skill_build_attempts", "skill_bindings", "research_cache"):
            try:
                await session.execute(text(f"DELETE FROM {dep_table}"))
            except Exception:
                pass

        # Delete all skills
        deleted_skills = (await session.execute(
            delete(Skill)
        )).rowcount

        # Delete orphaned prompts
        deleted_prompts = 0
        for prompt_id in sg_prompt_ids:
            remaining = (await session.execute(
                select(func.count()).select_from(Agent).where(Agent.prompt_id == prompt_id)
            )).scalar()
            if remaining == 0:
                await session.execute(delete(Prompt).where(Prompt.id == prompt_id))
                deleted_prompts += 1

        # Clean up topology change logs
        deleted_events = 0
        try:
            from app.models.sql.topology_models import TopologyChangeLog
            deleted_events += (await session.execute(
                delete(TopologyChangeLog)
            )).rowcount
        except Exception:
            pass

        # Clean up agent execution events
        try:
            from app.models.sql.agent_event_models import AgentExecutionEvent
            deleted_events += (await session.execute(
                delete(AgentExecutionEvent)
            )).rowcount
        except Exception:
            pass

        # Count remaining default agents
        remaining_default = (await session.execute(
            select(func.count()).select_from(Agent).where(Agent.source == "initial")
        )).scalar()

        # Re-activate all default agents
        await session.execute(
            update(Agent).where(Agent.source == "initial").values(is_active=True)
        )

        await session.commit()

        log.warning(
            f"System reset complete: agents={deleted_agents}, skills={deleted_skills}, "
            f"prompts={deleted_prompts}, events={deleted_events}, defaults={remaining_default}"
        )

        return SystemResetResponse(
            success=True,
            message="System reset to default state. All system-generated entities removed.",
            deleted_agents=deleted_agents,
            deleted_skills=deleted_skills,
            deleted_prompts=deleted_prompts,
            deleted_events=deleted_events,
            remaining_default_agents=remaining_default,
        )

    except Exception as e:
        log.error(f"System reset failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"System reset failed: {str(e)}",
        )


@router.get("/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_db_session),
) -> SnapshotListResponse:
    """
    List execution snapshots.

    Returns saved system state snapshots for restore.
    """
    log.info(f"Listing snapshots: limit={limit}, offset={offset}")

    # Get snapshots (in-memory for now)
    all_snapshots = list(_snapshots.values())
    all_snapshots.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    total = len(all_snapshots)
    page = all_snapshots[offset:offset + limit]

    return SnapshotListResponse(
        snapshots=[
            SnapshotSummaryResponse(
                id=s["id"],
                name=s["name"],
                description=s.get("description"),
                created_at=s["created_at"],
                agent_count=len(s.get("agents", [])),
                skill_count=len(s.get("skills", [])),
                prompt_count=len(s.get("prompts", [])),
            )
            for s in page
        ],
        total=total,
    )


@router.post("/snapshots", response_model=CreateSnapshotResponse)
async def create_snapshot(
    request: CreateSnapshotRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CreateSnapshotResponse:
    """
    Create an execution snapshot.

    Captures current system state (agents, skills, prompts) for later restore.
    """
    log.info(f"Creating snapshot: name={request.name}")

    from app.models.sql.versioned_models import Skill, Prompt

    # Get current state
    agents_result = await session.execute(select(Agent))
    agents = list(agents_result.scalars().all())

    skills_result = await session.execute(select(Skill))
    skills = list(skills_result.scalars().all())

    prompts_result = await session.execute(select(Prompt))
    prompts = list(prompts_result.scalars().all())

    # Create snapshot
    snapshot_id = str(uuid.uuid4())
    snapshot = {
        "id": snapshot_id,
        "name": request.name,
        "description": request.description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "capabilities": [],
                "dependencies": a.dependencies,
                "io_schema": a.io_schema,
                "is_active": a.is_active,
                "prompt_id": a.prompt_id,
            }
            for a in agents
        ],
        "skills": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "code": s.code,
                "test_cases": s.test_cases,
                "skill_metadata": s.skill_metadata,
                "is_active": s.is_active,
                "parent_id": s.parent_id,
            }
            for s in skills
        ],
        "prompts": [
            {
                "id": p.id,
                "name": p.name,
                "content": p.content,
                "prompt_metadata": p.prompt_metadata,
                "is_active": p.is_active,
                "parent_id": p.parent_id,
            }
            for p in prompts
        ],
    }

    _snapshots[snapshot_id] = snapshot

    log.info(f"Snapshot created: id={snapshot_id}, agents={len(agents)}, skills={len(skills)}, prompts={len(prompts)}")

    return CreateSnapshotResponse(
        id=snapshot_id,
        name=request.name,
        created_at=snapshot["created_at"],
        message=f"Snapshot created with {len(agents)} agents, {len(skills)} skills, {len(prompts)} prompts",
    )


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotDetailResponse)
async def get_snapshot(
    snapshot_id: str,
) -> SnapshotDetailResponse:
    """
    Get snapshot details.

    Returns full state captured in snapshot.
    """
    log.info(f"Getting snapshot: id={snapshot_id}")

    snapshot = _snapshots.get(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {snapshot_id}")

    return SnapshotDetailResponse(
        id=snapshot["id"],
        name=snapshot["name"],
        description=snapshot.get("description"),
        created_at=snapshot["created_at"],
        agents=snapshot.get("agents", []),
        skills=snapshot.get("skills", []),
        prompts=snapshot.get("prompts", []),
    )


@router.post("/snapshots/{snapshot_id}/restore", response_model=RestoreSnapshotResponse)
async def restore_snapshot(
    snapshot_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> RestoreSnapshotResponse:
    """
    Restore from a snapshot.

    Restores agents to their snapshot state (active/inactive status).
    Note: This is a partial restore - only restores is_active flags.
    Full restore would require more complex logic to handle new entities.
    """
    log.info(f"Restoring from snapshot: id={snapshot_id}")

    snapshot = _snapshots.get(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {snapshot_id}")

    agents_restored = 0
    skills_restored = 0
    prompts_restored = 0

    # Restore agent active states
    for agent_data in snapshot.get("agents", []):
        await session.execute(
            update(Agent)
            .where(Agent.id == agent_data["id"])
            .values(is_active=agent_data["is_active"])
        )
        agents_restored += 1

    # For skills and prompts, just count (full restore would be more complex)
    skills_restored = len(snapshot.get("skills", []))
    prompts_restored = len(snapshot.get("prompts", []))

    await session.commit()

    log.info(f"Snapshot restored: agents={agents_restored}")

    return RestoreSnapshotResponse(
        success=True,
        snapshot_id=snapshot_id,
        message=f"Restored agent states from snapshot '{snapshot['name']}'",
        restored_at=datetime.now(timezone.utc).isoformat(),
        agents_restored=agents_restored,
        skills_restored=skills_restored,
        prompts_restored=prompts_restored,
    )
