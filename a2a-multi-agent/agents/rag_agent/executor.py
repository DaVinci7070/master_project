
from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from a2a_common.schemas.rag import RAGInput, RAGOutput
from a2a_common.executor_utils import extract_input_model, send_output_model
from a2a_common.signals import create_error_signal
from a2a_common.logging import get_logger

from .retrieving import retrieve_for_inputs

logger = get_logger(__name__)

class RAGExecutor(AgentExecutor):

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("RAG Agent: execution started")

        try:
            inputs = extract_input_model(context, RAGInput)
            logger.debug(f"Received inputs: user_id={inputs.user_id}, transcript len={len(inputs.transcript)}")

            context_documents = await retrieve_for_inputs(inputs)

            output = RAGOutput(context_documents=context_documents)

            await send_output_model(event_queue, output)
            logger.info(f"RAG Agent: returned {len(context_documents)} documents")

        except Exception as exc:
            logger.error(f"RAG Agent: execution error: {exc}", exc_info=True)

            error_output = RAGOutput(context_documents=[])
            error_signal = create_error_signal(
                reason=str(exc),
                error_details={"type": exc.__class__.__name__}
            )
            await send_output_model(event_queue, error_output, error_signal)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("RAG Agent: cancel requested")
