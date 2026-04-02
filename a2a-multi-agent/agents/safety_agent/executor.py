
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.safety import SafetyInput, SafetyOutput, SafetyResult
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .safety_analysis import analyze_safety


logger = get_logger(__name__)


class SafetyAgentExecutor(AgentExecutor):
    """Executor für den Safety Agent."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Safety Agent: Execution gestartet")

        try:

            inputs = extract_input_model(context, SafetyInput)
            logger.debug(f"Transkript erhalten, Länge: {len(inputs.transcript)} Zeichen")


            result = await analyze_safety(transcript=inputs.transcript)


            safety_result = SafetyResult(
                incidents=[
                    {
                        "type": incident.type,
                        "description": incident.description,
                        "severity": incident.severity,
                        "location": incident.location,
                        "people_involved": incident.people_involved,
                        "psa_related": incident.psa_related,
                    }
                    for incident in result.report.incidents
                ],
                incident_count=result.report.incident_count,
                critical_count=result.report.critical_count,
                accident_count=result.report.accident_count,
                compliance_status=result.report.compliance_status,
                summary=result.summary,
            )

            output = SafetyOutput(safety_result=safety_result)

            await send_output_model(event_queue, output)
            logger.info(
                f"Safety Agent: Analyse abgeschlossen, "
                f"{safety_result.incident_count} Vorfälle gefunden, "
                f"davon {safety_result.critical_count} kritisch, "
                f"Compliance: {safety_result.compliance_status}"
            )

        except Exception as exc:
            logger.error(f"Safety Agent: Execution-Fehler: {exc}", exc_info=True)

            error_output = SafetyOutput(
                safety_result=SafetyResult(
                    incidents=[],
                    incident_count=0,
                    critical_count=0,
                    accident_count=0,
                    compliance_status="compliant",
                    summary=f"Fehler bei der Sicherheitsanalyse: {str(exc)}"
                )
            )
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Safety Agent: Cancel angefordert")
