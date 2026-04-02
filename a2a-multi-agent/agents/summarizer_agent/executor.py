
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.summarizer import SummarizerInput, SummarizerOutput
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .summarization import summarize_report

logger = get_logger(__name__)

class SummarizerAgentExecutor(AgentExecutor):

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Summarizer Agent: execution started")

        try:
            inputs = extract_input_model(context, SummarizerInput)
            ctx_count = len(inputs.context_documents or [])
            logger.info(
                f"Summarizer: Received inputs: transcript_len={len(inputs.transcript)}, "
                f"context_docs_count={ctx_count}, "
                f"has_template={'yes' if inputs.template_result else 'no'}"
            )
            if ctx_count > 0 and inputs.context_documents:
                logger.info(f"Summarizer: Context documents preview: {[d.get('title', 'N/A')[:50] for d in inputs.context_documents[:3]]}")


            specialized_data = {}
            if inputs.defect_list:
                specialized_data["defect_list"] = inputs.defect_list
            if inputs.safety_report:
                specialized_data["safety_report"] = inputs.safety_report
            if inputs.claim_report:
                specialized_data["claim_report"] = inputs.claim_report
            if inputs.quality_report:
                specialized_data["quality_report"] = inputs.quality_report

            logger.info(f"Summarizer: Found specialized data for: {list(specialized_data.keys())}")

            report = await summarize_report(
                transcript=inputs.transcript,
                context_documents=inputs.context_documents,
                template_result=inputs.template_result,
                specialized_data=specialized_data
            )

            output = SummarizerOutput(summary_report=report)

            await send_output_model(event_queue, output)
            logger.info(f"Summarizer Agent: generated report of length {len(report)}")

        except Exception as exc:
            logger.error(f"Summarizer Agent: execution error: {exc}", exc_info=True)

            error_output = SummarizerOutput(summary_report=f"Error: {exc}")
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Summarizer Agent: cancel requested")