import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies.dependencies import get_db_session
from app.models.sql.shared_memory_models import Fact, Hypothesis

router = APIRouter(prefix="/shared-memory", tags=["shared-memory"])
log = logging.getLogger(__name__)


@router.get("/execution/{execution_id}")
async def get_execution_shared_memory(
    execution_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get all shared memory content for an execution.

    Returns facts and hypotheses written during the specified execution,
    grouped by source agent.
    """
    log.info(f"Fetching shared memory for execution: {execution_id}")

    facts = []
    hypotheses = []

    try:
        facts_stmt = select(Fact).where(
            Fact.execution_id == execution_id
        ).order_by(Fact.created_at.asc())

        facts_result = await session.execute(facts_stmt)
        facts = list(facts_result.scalars().all())
    except Exception as e:
        log.warning(f"Failed to fetch facts (table may not exist): {e}")
        try:
            await session.rollback()
        except Exception:
            pass

    try:
        hypotheses_stmt = select(Hypothesis).where(
            Hypothesis.execution_id == execution_id
        ).order_by(Hypothesis.created_at.asc())

        hypotheses_result = await session.execute(hypotheses_stmt)
        hypotheses = list(hypotheses_result.scalars().all())
    except Exception as e:
        log.warning(f"Failed to fetch hypotheses (table may not exist): {e}")
        try:
            await session.rollback()
        except Exception:
            pass

    facts_by_agent: dict[str, list] = {}
    for fact in facts:
        agent_id = fact.source_agent_id or "unknown"
        if agent_id not in facts_by_agent:
            facts_by_agent[agent_id] = []
        facts_by_agent[agent_id].append({
            "id": fact.id,
            "text": fact.text,
            "confidence": fact.confidence,
            "tags": fact.tags,
            "created_at": fact.created_at.isoformat() if fact.created_at else None,
        })

    hypotheses_by_agent: dict[str, list] = {}
    for hyp in hypotheses:
        agent_id = hyp.source_agent_id or "unknown"
        if agent_id not in hypotheses_by_agent:
            hypotheses_by_agent[agent_id] = []
        hypotheses_by_agent[agent_id].append({
            "id": hyp.id,
            "text": hyp.text,
            "confidence": hyp.confidence,
            "status": hyp.status,
            "supporting_fact_ids": hyp.supporting_fact_ids,
            "contradicting_fact_ids": hyp.contradicting_fact_ids,
            "created_at": hyp.created_at.isoformat() if hyp.created_at else None,
        })

    return {
        "execution_id": execution_id,
        "facts": {
            "total": len(facts),
            "by_agent": facts_by_agent,
            "items": [
                {
                    "id": f.id,
                    "text": f.text,
                    "confidence": f.confidence,
                    "source_agent_id": f.source_agent_id,
                    "tags": f.tags,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in facts
            ],
        },
        "hypotheses": {
            "total": len(hypotheses),
            "by_agent": hypotheses_by_agent,
            "items": [
                {
                    "id": h.id,
                    "text": h.text,
                    "confidence": h.confidence,
                    "status": h.status,
                    "source_agent_id": h.source_agent_id,
                    "supporting_fact_ids": h.supporting_fact_ids,
                    "contradicting_fact_ids": h.contradicting_fact_ids,
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                }
                for h in hypotheses
            ],
        },
    }


@router.get("/execution/{execution_id}/facts")
async def get_execution_facts(
    execution_id: str,
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get only facts for an execution.

    Optionally filter by minimum confidence threshold.
    """
    facts = []

    try:
        stmt = select(Fact).where(Fact.execution_id == execution_id)

        if min_confidence is not None:
            stmt = stmt.where(Fact.confidence >= min_confidence)

        stmt = stmt.order_by(Fact.created_at.asc())

        result = await session.execute(stmt)
        facts = list(result.scalars().all())
    except Exception as e:
        log.warning(f"Failed to fetch facts (table may not exist): {e}")
        try:
            await session.rollback()
        except Exception:
            pass

    return {
        "execution_id": execution_id,
        "total": len(facts),
        "facts": [
            {
                "id": f.id,
                "text": f.text,
                "confidence": f.confidence,
                "source_agent_id": f.source_agent_id,
                "tags": f.tags,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facts
        ],
    }


@router.get("/execution/{execution_id}/hypotheses")
async def get_execution_hypotheses(
    execution_id: str,
    status: Optional[str] = Query(None, description="Filter by status: active, confirmed, contradicted"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get only hypotheses for an execution.

    Optionally filter by status.
    """
    hypotheses = []

    try:
        stmt = select(Hypothesis).where(Hypothesis.execution_id == execution_id)

        if status:
            stmt = stmt.where(Hypothesis.status == status)

        stmt = stmt.order_by(Hypothesis.created_at.asc())

        result = await session.execute(stmt)
        hypotheses = list(result.scalars().all())
    except Exception as e:
        log.warning(f"Failed to fetch hypotheses (table may not exist): {e}")
        try:
            await session.rollback()
        except Exception:
            pass

    return {
        "execution_id": execution_id,
        "total": len(hypotheses),
        "hypotheses": [
            {
                "id": h.id,
                "text": h.text,
                "confidence": h.confidence,
                "status": h.status,
                "source_agent_id": h.source_agent_id,
                "supporting_fact_ids": h.supporting_fact_ids,
                "contradicting_fact_ids": h.contradicting_fact_ids,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in hypotheses
        ],
    }
