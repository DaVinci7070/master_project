"""
Analysis Pipeline for orchestrating post-execution analysis.

This service orchestrates the full analysis flow:
Analyzer -> Store findings -> Product Owner -> Update priorities.

Analysis runs automatically after every successful execution,
triggered via TelemetryService callback, and runs asynchronously
via FastAPI BackgroundTasks to avoid blocking the main execution response.
"""
import logging
from typing import Optional

from app.core.llm_client import LLMClient
from app.models.schemas.analysis_schemas import (
    AnalysisFindingCreate,
    AnalysisFindingResponse,
    PriorityList,
)
from app.repositories.finding_repository import FindingRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.services.analyzer_service import AnalyzerService
from app.services.product_owner_service import ProductOwnerService
from app.services.telemetry_service import TelemetryService

log = logging.getLogger(__name__)


class AnalysisPipeline:
    """
    Orchestrates post-execution analysis: Analyzer -> Product Owner -> Storage.

    Flow:
    1. Get execution telemetry and history
    2. Run Analyzer to generate findings
    3. Store findings in database
    4. Run Product Owner for prioritization
    5. Update findings with priorities

    Example:
        pipeline = AnalysisPipeline(
            telemetry_service=telemetry_svc,
            analyzer_service=analyzer_svc,
            product_owner_service=po_svc,
            finding_repository=finding_repo,
        )

        findings = await pipeline.run(
            execution_id="exec-123",
            input_content="user query",
            output_content="agent response",
        )
    """

    def __init__(
        self,
        telemetry_service: TelemetryService,
        analyzer_service: AnalyzerService,
        product_owner_service: ProductOwnerService,
        finding_repository: FindingRepository,
    ):
        """
        Initialize the analysis pipeline.

        Args:
            telemetry_service: Service for telemetry data access.
            analyzer_service: Analyzer agent for generating findings.
            product_owner_service: Product Owner agent for prioritization.
            finding_repository: Repository for storing findings.
        """
        self.telemetry = telemetry_service
        self.analyzer = analyzer_service
        self.product_owner = product_owner_service
        self.finding_repo = finding_repository

    async def run(
        self,
        execution_id: str,
        input_content: Optional[str] = None,
        output_content: Optional[str] = None,
    ) -> tuple[list[AnalysisFindingResponse], PriorityList]:
        """
        Run full analysis pipeline for an execution.

        This method orchestrates the complete analysis flow:
        1. Retrieves telemetry for the execution
        2. Gets historical telemetry for pattern detection
        3. Runs Analyzer to generate findings
        4. Stores findings in the database
        5. Runs Product Owner for prioritization
        6. Updates findings with assigned priorities

        Args:
            execution_id: ID of the completed execution.
            input_content: Optional full input content (for evidence).
            output_content: Optional full output content (for evidence).

        Returns:
            List of stored findings with priorities assigned.
            Returns empty list if telemetry not found or analysis fails.
        """
        log.info(f"Starting analysis pipeline for execution_id={execution_id[:8]}...")

        # Empty priority list used for early-return paths
        empty_priorities = PriorityList(
            priorities=[],
            improvement_direction="no findings",
        )

        # Step 1: Get telemetry for this execution
        telemetry = await self.telemetry.get_by_execution_id(execution_id)
        if not telemetry:
            log.warning(f"No telemetry found for execution {execution_id}")
            return [], empty_priorities

        log.info(
            f"Retrieved telemetry for agent={telemetry.agent_id[:8]}..., "
            f"outcome={telemetry.outcome}"
        )

        # Step 2: Get historical telemetry for pattern detection (N=10)
        history = await self.telemetry.get_execution_history(
            agent_id=telemetry.agent_id,
            limit=10,
        )
        log.info(f"Retrieved {len(history)} historical executions for pattern context")

        # Step 3: Run Analyzer to generate findings
        analysis = await self.analyzer.analyze_execution(
            telemetry=telemetry,
            history=history,
            input_content=input_content,
            output_content=output_content,
        )
        log.info(
            f"Analyzer generated {len(analysis.findings)} findings: "
            f"summary='{analysis.summary[:50]}...'"
        )

        if not analysis.findings:
            log.info("No findings generated - pipeline complete")
            return [], empty_priorities

        # Step 4: Store findings in database
        stored_findings = []
        for finding in analysis.findings:
            create_data = AnalysisFindingCreate(
                execution_telemetry_id=execution_id,
                category=finding.category,
                severity=finding.severity,
                evidence=finding.evidence,
                suggested_fix=finding.suggested_fix,
                input_content=input_content,
                output_content=output_content,
            )
            stored = await self.finding_repo.create(create_data)
            stored_findings.append(stored)

        log.info(f"Stored {len(stored_findings)} findings in database")

        # Step 5: Run Product Owner for prioritization
        priorities = await self.product_owner.prioritize_findings(
            current_findings=analysis.findings,
            execution_id=execution_id,
            agent_id=telemetry.agent_id,
        )
        log.info(
            f"Product Owner prioritized {len(priorities.priorities)} items: "
            f"direction='{priorities.improvement_direction[:50]}...'"
        )

        # Step 6: Update findings with priorities
        for priority in priorities.priorities:
            if priority.finding_index < len(stored_findings):
                finding = stored_findings[priority.finding_index]
                await self.finding_repo.update_priority(
                    finding_id=finding.id,
                    priority_rank=priority.priority_rank,
                )

        log.info(
            f"Analysis pipeline complete for execution_id={execution_id[:8]}..., "
            f"findings={len(stored_findings)}"
        )

        # Return findings as response schemas + the PriorityList for downstream
        # consumers like the Evolution Loop (Sprint 1).
        response = [
            AnalysisFindingResponse.model_validate(f)
            for f in stored_findings
        ]
        return response, priorities


async def run_analysis_pipeline(
    execution_id: str,
    input_content: Optional[str] = None,
    output_content: Optional[str] = None,
) -> None:
    """
    Background task function for running analysis pipeline.

    Creates all required dependencies and runs the pipeline.
    Catches all exceptions to prevent background task crashes.

    This function is designed to be called via FastAPI BackgroundTasks:

        async def trigger_analysis(execution_id: str):
            background_tasks.add_task(
                run_analysis_pipeline,
                execution_id,
                input_content="...",
                output_content="...",
            )

        await telemetry_service.complete_execution(
            telemetry_id=telemetry.id,
            output_data=result,
            on_complete=trigger_analysis,
        )

    Args:
        execution_id: ID of the completed execution.
        input_content: Optional full input content (for evidence).
        output_content: Optional full output content (for evidence).
    """
    log.info(f"Background task: starting analysis for execution_id={execution_id[:8]}...")

    try:
        # Import dependencies inside function to avoid circular imports
        from app.dependencies.dependencies import AsyncSessionLocal
        from app.core.llm_client import LLMClient

        async with AsyncSessionLocal() as session:
            # Create repositories
            telemetry_repo = TelemetryRepository(session)
            finding_repo = FindingRepository(session)

            # Create services
            telemetry_service = TelemetryService(telemetry_repo)
            llm_client = LLMClient()
            analyzer = AnalyzerService(llm_client)
            product_owner = ProductOwnerService(llm_client, finding_repo)

            # Create and run pipeline
            pipeline = AnalysisPipeline(
                telemetry_service=telemetry_service,
                analyzer_service=analyzer,
                product_owner_service=product_owner,
                finding_repository=finding_repo,
            )

            # Tuple return; we discard it here — the existing callback flow
            # only needs the side effects (DB writes of findings + priorities).
            await pipeline.run(execution_id, input_content, output_content)

        log.info(f"Background task: analysis complete for execution_id={execution_id[:8]}...")

    except Exception as e:
        # Catch all exceptions to prevent background task crashes
        # Log the error but don't re-raise
        log.error(
            f"Analysis pipeline failed for execution {execution_id}: {e}",
            exc_info=True,
        )
