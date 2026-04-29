from typing import AsyncGenerator, Callable
from fastapi import Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Session-Factory Typ: jede DB-Operation öffnet eigene kurzlebige Session
SessionFactory = Callable[..., AsyncSession]

from app.core.config import settings
from app.services.template_service import TemplateService
from app.repositories.qdrant_repository import QdrantReportsRepository

async_engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True
)

AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

def get_qdrant_repository() -> QdrantReportsRepository:
    return QdrantReportsRepository(
        qdrant_url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        prefer_grpc=False,
        embed_model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        collection_prefix=settings.qdrant_collection,
    )

def get_template_service(
    repository: QdrantReportsRepository = Depends(get_qdrant_repository),
) -> TemplateService:
    return TemplateService(
        qdrant_repo=repository,
    )


async def get_orchestrator(
    db: AsyncSession = Depends(get_db_session)
):
    """
    Factory for HybridOrchestrator with telemetry support.

    Creates an initialized orchestrator ready for challenge execution.
    """
    from app.core.llm_client import LLMClient
    from app.orchestration.orchestrators.hybrid_orchestrator import HybridOrchestrator

    llm = LLMClient()
    orchestrator = HybridOrchestrator(db=db, llm_client=llm)
    await orchestrator.initialize()
    return orchestrator


def get_telemetry_service(
    session: AsyncSession = Depends(get_db_session)
):
    """Factory for TelemetryService."""
    from app.repositories.telemetry_repository import TelemetryRepository
    from app.services.telemetry_service import TelemetryService

    repository = TelemetryRepository(session)
    return TelemetryService(repository)
