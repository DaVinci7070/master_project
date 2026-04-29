"""
DI helpers for the Autonomous Evolution Loop (Sprint 1).

Provides both:
- build_evolution_loop_service(session): plain builder for the background task
  spawned by HybridOrchestrator (isolated session).
- get_evolution_loop_service(): FastAPI Depends factory for API endpoints.
"""
import logging

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import LLMClient
from app.dependencies.dependencies import get_db_session
from app.repositories.ab_test_repository import ABTestRepository
from app.repositories.finding_repository import FindingRepository
from app.repositories.improvement_repository import ImprovementRepository
from app.repositories.prompt_repository import PromptRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.services.ab_test_service import ABTestService
from app.services.analysis_pipeline import AnalysisPipeline
from app.services.analyzer_service import AnalyzerService
from app.services.code_validator_service import CodeValidatorService
from app.services.control_agent_service import ControlAgentService
from app.services.evolution_loop_service import EvolutionLoopService
from app.services.improvement_orchestrator import ImprovementOrchestrator
from app.services.product_owner_service import ProductOwnerService
from app.services.prompt_engineer_service import PromptEngineerService
from app.services.quality_judge_service import QualityJudgeService
from app.services.rollback_service import RollbackService
from app.services.sandbox_executor_service import SandboxExecutorService
from app.services.statistical_analyzer import StatisticalAnalyzer
from app.services.telemetry_service import TelemetryService
from app.services.tool_builder_service import ToolBuilderService
from app.services.version_service import VersionService

log = logging.getLogger(__name__)


def build_evolution_loop_service(
    session: AsyncSession,
) -> EvolutionLoopService:
    """Build EvolutionLoopService with all dependencies.

    Used from the HybridOrchestrator background task (with an isolated session)
    AND from API endpoints (via FastAPI Depends).
    """
    llm_client = LLMClient()

    # Repositories
    telemetry_repo = TelemetryRepository(session)
    finding_repo = FindingRepository(session)
    improvement_repo = ImprovementRepository(session)
    prompt_repo = PromptRepository(session)
    ab_test_repo = ABTestRepository(session)

    # AnalysisPipeline (analyzer + product owner + findings storage)
    telemetry_service = TelemetryService(telemetry_repo)
    analyzer = AnalyzerService(llm_client)
    product_owner = ProductOwnerService(llm_client, finding_repo)
    analysis_pipeline = AnalysisPipeline(
        telemetry_service=telemetry_service,
        analyzer_service=analyzer,
        product_owner_service=product_owner,
        finding_repository=finding_repo,
    )

    # ControlAgent
    control_agent = ControlAgentService(
        llm_client=llm_client,
        improvement_repo=improvement_repo,
        finding_repo=finding_repo,
    )

    # ImprovementOrchestrator (prompts + A/B tests; skills optional best-effort)
    prompt_engineer = PromptEngineerService(llm_client, prompt_repo)

    # A/B testing stack — needs quality judge, stats, and rollback plumbing.
    version_service = VersionService(session)
    quality_judge = QualityJudgeService(llm_client)
    statistical_analyzer = StatisticalAnalyzer()
    rollback_service = RollbackService(version_service, improvement_repo)
    ab_test_service = ABTestService(
        ab_test_repo=ab_test_repo,
        improvement_repo=improvement_repo,
        quality_judge=quality_judge,
        statistical_analyzer=statistical_analyzer,
        rollback_service=rollback_service,
    )

    # Phase-6 Services: Skill-Improvement (graceful degradation)
    code_validator = CodeValidatorService()
    skill_repo = None
    tool_builder = None
    sandbox_executor = None
    try:
        skill_repo = SkillRepository(session)
        tool_builder = ToolBuilderService(
            llm_client=llm_client,
            code_validator=code_validator,
            skill_repo=skill_repo,
        )
        sandbox_executor = SandboxExecutorService(code_validator=code_validator)
    except Exception as e:
        log.warning(f"Skill-Improvement-Services nicht verfügbar: {e}")

    improvement_orchestrator = ImprovementOrchestrator(
        improvement_repo=improvement_repo,
        prompt_engineer=prompt_engineer,
        prompt_repo=prompt_repo,
        ab_test_service=ab_test_service,
        tool_builder=tool_builder,
        sandbox_executor=sandbox_executor,
        skill_repo=skill_repo,
    )

    return EvolutionLoopService(
        db=session,
        analysis_pipeline=analysis_pipeline,
        control_agent=control_agent,
        improvement_orchestrator=improvement_orchestrator,
        improvement_repo=improvement_repo,
    )


def get_evolution_loop_service(
    session: AsyncSession = Depends(get_db_session),
) -> EvolutionLoopService:
    """FastAPI Depends factory for endpoints."""
    return build_evolution_loop_service(session)