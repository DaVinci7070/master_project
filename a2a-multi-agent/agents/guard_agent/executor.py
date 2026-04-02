
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.guard import GuardInput, GuardOutput
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .guarding import guard_report

logger = get_logger(__name__)

class GuardAgentExecutor(AgentExecutor):

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Guard Agent: execution started")

        try:
            inputs = extract_input_model(context, GuardInput)
            logger.debug(
                f"Received inputs: transcript len={len(inputs.transcript)}, "
                f"report len={len(inputs.report)}"
            )

            result = await guard_report(
                transcript=inputs.transcript,
                report=inputs.report,
                context_documents=inputs.context_documents or []
            )

            corrections_list = None
            if result.issues:
                corrections_list = [issue.reason for issue in result.issues]
            output = GuardOutput(
                corrected_report=result.corrected_report,
                corrections_made=corrections_list
            )

            await send_output_model(event_queue, output)
            logger.info(
                f"Guard Agent: report validated, "
                f"hallucinations={'yes' if result.has_hallucinations else 'no'}"
            )

        except Exception as exc:
            logger.error(f"Guard Agent: execution error: {exc}", exc_info=True)

            error_output = GuardOutput(corrected_report="", corrections_made=None)
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Guard Agent: cancel requested")