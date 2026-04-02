
from __future__ import annotations

from typing import Any

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a_common.logging import setup_logging, get_logger
from .agent_card import PUBLIC_AGENT_CARD  
from .executor import OrchestratorAgentExecutor

setup_logging()
logger = get_logger(__name__)

def create_app() -> Any:
    logger.info("Starte Orchestrator-Agent-App...")

    request_handler = DefaultRequestHandler(
        agent_executor=OrchestratorAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    app = A2AStarletteApplication(
        agent_card=PUBLIC_AGENT_CARD,
        http_handler=request_handler,
    )

    return app.build()
