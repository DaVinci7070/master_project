"""
API endpoints for agent management.

Provides CRUD operations for agents including status toggling.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.dependencies import get_db_session
from app.repositories.topology_repository import TopologyRepository
from app.repositories.prompt_repository import PromptRepository
from app.repositories.skill_repository import SkillRepository

router = APIRouter(prefix="/agents", tags=["agents"])
log = logging.getLogger(__name__)


# Response models
class PromptSummary(BaseModel):
    """Summary of a prompt for agent responses."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    content: str
    is_active: bool


class SkillSummary(BaseModel):
    """Summary of a skill for agent responses."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    is_active: bool


class AgentResponse(BaseModel):
    """Agent response model."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    io_schema: dict = Field(default_factory=dict)
    is_active: bool
    prompt_id: Optional[str] = None
    source: str = "initial"  # initial, system_generated, manual
    agent_metadata: Optional[dict] = None
    created_at: str


class AgentDetailResponse(BaseModel):
    """Detailed agent response including prompt and skills."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    io_schema: dict = Field(default_factory=dict)
    is_active: bool
    prompt_id: Optional[str] = None
    source: str = "initial"
    agent_metadata: Optional[dict] = None
    created_at: str
    prompt: Optional[PromptSummary] = None
    skills: list[SkillSummary] = Field(default_factory=list)


class AgentStatusUpdate(BaseModel):
    """Request to update agent status."""
    is_active: bool


class AgentListResponse(BaseModel):
    """Paginated agent list response."""
    agents: list[AgentResponse]
    total: int
    limit: int
    offset: int


@router.get("", response_model=AgentListResponse)
async def list_agents(
    status: Optional[str] = Query(None, description="Filter by status: active, inactive"),
    search: Optional[str] = Query(None, description="Search by name"),
    limit: int = Query(50, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_db_session),
) -> AgentListResponse:
    """
    List all agents with optional filtering.

    Supports filtering by active status and searching by name.
    """
    log.info(f"Listing agents: status={status}, search={search}, limit={limit}, offset={offset}")

    repo = TopologyRepository(session)

    # Get all agents (active only if status filter is "active")
    if status == "active":
        agents = await repo.get_all_active_agents()
    else:
        # Get all agents regardless of status
        from sqlalchemy import select
        from app.models.sql.versioned_models import Agent
        result = await session.execute(select(Agent))
        agents = list(result.scalars().all())

    # Apply status filter for inactive
    if status == "inactive":
        agents = [a for a in agents if not a.is_active]

    # Apply search filter
    if search:
        search_lower = search.lower()
        agents = [a for a in agents if search_lower in a.name.lower()]

    total = len(agents)

    # Apply pagination
    agents = agents[offset:offset + limit]

    return AgentListResponse(
        agents=[
            AgentResponse(
                id=a.id,
                name=a.name,
                capabilities=[],
                dependencies=a.dependencies or [],
                io_schema=a.io_schema or {},
                is_active=a.is_active,
                prompt_id=a.prompt_id,
                source=a.source or "initial",
                agent_metadata=a.agent_metadata,
                created_at=a.created_at.isoformat() if a.created_at else "",
            )
            for a in agents
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{agent_id}", response_model=AgentDetailResponse)
async def get_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AgentDetailResponse:
    """
    Get agent by ID with prompt and skills.

    Returns 404 if agent not found.
    """
    log.info(f"Getting agent: id={agent_id}")

    repo = TopologyRepository(session)
    agent = await repo.get_agent_by_id(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    # Get associated prompt
    prompt = None
    if agent.prompt_id:
        prompt_repo = PromptRepository(session)
        prompt_model = await prompt_repo.get_by_id(agent.prompt_id)
        if prompt_model:
            prompt = PromptSummary(
                id=prompt_model.id,
                name=prompt_model.name,
                content=prompt_model.content,
                is_active=prompt_model.is_active,
            )

    # Get skills (from io_schema.skill_ids if present)
    skills = []
    skill_ids = agent.io_schema.get("skill_ids", []) if agent.io_schema else []
    if skill_ids:
        skill_repo = SkillRepository(session)
        for skill_id in skill_ids:
            skill = await skill_repo.get_by_id(skill_id)
            if skill:
                skills.append(SkillSummary(
                    id=skill.id,
                    name=skill.name,
                    description=skill.description,
                    is_active=skill.is_active,
                ))

    return AgentDetailResponse(
        id=agent.id,
        name=agent.name,
        capabilities=[],
        dependencies=agent.dependencies or [],
        io_schema=agent.io_schema or {},
        is_active=agent.is_active,
        prompt_id=agent.prompt_id,
        source=agent.source or "initial",
        agent_metadata=agent.agent_metadata,
        created_at=agent.created_at.isoformat() if agent.created_at else "",
        prompt=prompt,
        skills=skills,
    )


@router.patch("/{agent_id}/status", response_model=AgentResponse)
async def toggle_agent_status(
    agent_id: str,
    status_update: AgentStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """
    Toggle agent active/inactive status.

    Returns 404 if agent not found.
    """
    log.info(f"Updating agent status: id={agent_id}, is_active={status_update.is_active}")

    repo = TopologyRepository(session)
    agent = await repo.get_agent_by_id(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    # Update status
    from sqlalchemy import update
    from app.models.sql.versioned_models import Agent

    await session.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(is_active=status_update.is_active)
    )
    await session.commit()

    # Refresh agent
    agent = await repo.get_agent_by_id(agent_id)

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        capabilities=[],
        dependencies=agent.dependencies or [],
        io_schema=agent.io_schema or {},
        is_active=agent.is_active,
        prompt_id=agent.prompt_id,
        source=agent.source or "initial",
        agent_metadata=agent.agent_metadata,
        created_at=agent.created_at.isoformat() if agent.created_at else "",
    )
