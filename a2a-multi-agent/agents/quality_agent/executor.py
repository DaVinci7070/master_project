
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.quality import QualityInput, QualityOutput, QualityResult
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .quality_analysis import analyze_quality


logger = get_logger(__name__)

class QualityAgentExecutor(AgentExecutor):


    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Quality Agent: Execution gestartet")

        try:

            inputs = extract_input_model(context, QualityInput)
            logger.debug(f"Transkript erhalten, Länge: {len(inputs.transcript)} Zeichen")


            result = await analyze_quality(transcript=inputs.transcript)


            quality_result = QualityResult(
                materials_used=result.quality_check.materials_used,
                norms_mentioned=result.quality_check.norms_mentioned,
                issues=result.quality_check.issues,
                summary=result.summary,
            )

            output = QualityOutput(quality_result=quality_result)

            await send_output_model(event_queue, output)
            logger.info(
                f"Quality Agent: Analyse abgeschlossen, "
                f"{len(quality_result.materials_used)} Materialien, "
                f"{len(quality_result.norms_mentioned)} Normen, "
                f"{len(quality_result.issues)} Probleme"
            )

        except Exception as exc:
            logger.error(f"Quality Agent: Execution-Fehler: {exc}", exc_info=True)

            error_output = QualityOutput(
                quality_result=QualityResult(
                    materials_used=[],
                    norms_mentioned=[],
                    issues=[],
                    summary=f"Fehler bei der Qualitätsanalyse: {str(exc)}"
                )
            )
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Quality Agent: Cancel angefordert")
