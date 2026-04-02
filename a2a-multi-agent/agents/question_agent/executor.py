
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.question import QuestionInput, QuestionOutput
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .logic import analyze

logger = get_logger(__name__)

class QuestionAgentExecutor(AgentExecutor):

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Question Agent: execution started")

        try:
            inputs = extract_input_model(context, QuestionInput)
            logger.debug(
                f"Received inputs: transcript len={len(inputs.transcript)}, "
                f"template keys={list(inputs.template_result.keys()) if inputs.template_result else 'None'}"
            )

            output, signal = await analyze(inputs)

            await send_output_model(event_queue, output, signal)
            logger.info(
                f"Question Agent: response sent with signal={signal.signal if signal else 'None'}"
            )

        except Exception as exc:
            logger.error(f"Question Agent: execution error: {exc}", exc_info=True)

            error_output = QuestionOutput(question_result={})
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Question Agent: cancel requested")
