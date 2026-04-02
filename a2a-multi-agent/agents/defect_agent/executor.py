
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.defect import DefectInput, DefectOutput, DefectResult
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .defect_analysis import analyze_defects


logger = get_logger(__name__)


class DefectAgentExecutor(AgentExecutor):


    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Defect Agent: Execution gestartet")

        try:

            inputs = extract_input_model(context, DefectInput)
            logger.debug(f"Transkript erhalten, Länge: {len(inputs.transcript)} Zeichen")


            result = await analyze_defects(transcript=inputs.transcript)


            defect_result = DefectResult(
                defects=[
                    {
                        "location": defect.location,
                        "description": defect.description,
                        "severity": defect.severity,
                        "action_required": defect.action_required,
                    }
                    for defect in result.defects.items
                ],
                total_count=result.defects.total_count,
                critical_count=result.defects.critical_count,
                summary=result.summary,
            )

            output = DefectOutput(defect_result=defect_result)

            await send_output_model(event_queue, output)
            logger.info(
                f"Defect Agent: Analyse abgeschlossen, "
                f"{defect_result.total_count} Mängel gefunden, "
                f"davon {defect_result.critical_count} kritisch"
            )

        except Exception as exc:
            logger.error(f"Defect Agent: Execution-Fehler: {exc}", exc_info=True)

            error_output = DefectOutput(
                defect_result=DefectResult(
                    defects=[],
                    total_count=0,
                    critical_count=0,
                    summary=f"Fehler bei der Mängelanalyse: {str(exc)}"
                )
            )
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Defect Agent: Cancel angefordert")
