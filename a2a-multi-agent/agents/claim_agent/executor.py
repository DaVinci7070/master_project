
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.claim import ClaimInput, ClaimOutput, ClaimResult
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .claim_analysis import analyze_claims


logger = get_logger(__name__)


class ClaimAgentExecutor(AgentExecutor):


    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Claim Agent: Execution gestartet")

        try:

            inputs = extract_input_model(context, ClaimInput)
            logger.debug(f"Transkript erhalten, Länge: {len(inputs.transcript)} Zeichen")


            result = await analyze_claims(transcript=inputs.transcript)


            claim_result = ClaimResult(
                claims=[
                    {
                        "topic": claim.topic,
                        "justification": claim.justification,
                        "estimated_impact": claim.estimated_impact,
                        "claim_type": claim.claim_type,
                    }
                    for claim in result.claims.claims
                ],
                total_count=result.claims.total_count,
                nachtrag_count=result.claims.nachtrag_count,
                summary=result.summary,
            )

            output = ClaimOutput(claim_result=claim_result)

            await send_output_model(event_queue, output)
            logger.info(
                f"Claim Agent: Analyse abgeschlossen, "
                f"{claim_result.total_count} Claims gefunden, "
                f"davon {claim_result.nachtrag_count} Nachträge"
            )

        except Exception as exc:
            logger.error(f"Claim Agent: Execution-Fehler: {exc}", exc_info=True)

            error_output = ClaimOutput(
                claim_result=ClaimResult(
                    claims=[],
                    total_count=0,
                    nachtrag_count=0,
                    summary=f"Fehler bei der Claim-Analyse: {str(exc)}"
                )
            )
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Claim Agent: Cancel angefordert")
