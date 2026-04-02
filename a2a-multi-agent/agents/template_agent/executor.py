
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.template import TemplateInput, TemplateOutput
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .load_template import load_template_for_payload

logger = get_logger(__name__)

class TemplateAgentExecutor(AgentExecutor):

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Template Agent: execution started")

        try:
            inputs = extract_input_model(context, TemplateInput)
            logger.debug(f"Received inputs: transcript len={len(inputs.transcript)}, user_id={inputs.user_id}")

            template_result = await load_template_for_payload(
                transcript=inputs.transcript,
                user_id=inputs.user_id,
                template_id=inputs.template_id
            )

            output = TemplateOutput(template_result=template_result.model_dump())

            await send_output_model(event_queue, output)
            logger.info("Template Agent: response sent successfully")

        except Exception as exc:
            logger.error(f"Template Agent: execution error: {exc}", exc_info=True)

            error_output = TemplateOutput(template_result={})
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Template Agent: cancel requested")