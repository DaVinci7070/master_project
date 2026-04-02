from typing import AsyncGenerator
from functools import lru_cache
from fastapi import Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.report_service import ReportService
from app.services.template_service import TemplateService
from app.repositories.qdrant_repository import QdrantReportsRepository
from app.adapters.sql_protocols import ReportRepositoryProtocol
from app.repositories.postgres_repository import PostgresRepository
from app.adapters.orchestrator_adapter import OrchestratorAdapter

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

def get_postgres_repository(
    session: AsyncSession = Depends(get_db_session)
) ->  ReportRepositoryProtocol:

    return PostgresRepository(session=session)

def get_qdrant_repository() -> QdrantReportsRepository:
    return QdrantReportsRepository(
        qdrant_url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        prefer_grpc=False,
        embed_model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        collection_prefix=settings.qdrant_collection,
    )

@lru_cache(maxsize=1)
def get_orchestrator_adapter() -> OrchestratorAdapter:
    return OrchestratorAdapter(base_url=settings.orchestrator_url)

def get_template_service(
    repository: QdrantReportsRepository = Depends(get_qdrant_repository),
) -> TemplateService:
    return TemplateService(
        qdrant_repo=repository,
    )

def get_report_service(
    repository: QdrantReportsRepository = Depends(get_qdrant_repository),
    orchestrator: OrchestratorAdapter = Depends(get_orchestrator_adapter),
    postgres_repo: PostgresRepository = Depends(get_postgres_repository),
    template_service: TemplateService = Depends(get_template_service)
) -> ReportService:
    return ReportService(
        orchestrator=orchestrator,
        qdrant_repo=repository,
        postgres_repo=postgres_repo,
        template_service=template_service
    )

from app.services.assistant_service import AssistantService

def get_assistant_service(
    repository: QdrantReportsRepository = Depends(get_qdrant_repository),
    postgres_repo: PostgresRepository = Depends(get_postgres_repository)
) -> AssistantService:
    return AssistantService(
        qdrant_repo=repository,
        postgres_repo=postgres_repo
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
