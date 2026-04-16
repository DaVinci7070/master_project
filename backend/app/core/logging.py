import logging
import sys
import os
import structlog
from typing import Any, Dict

def setup_logging(level: str = "INFO", json_format: bool = None):

    if json_format is None:
        log_format = os.getenv("LOG_FORMAT", "pretty").lower()
        json_format = log_format == "json"

    level = os.getenv("LOG_LEVEL", level).upper()

    if json_format:
        shared_processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]
    else:
        shared_processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.processors.format_exc_info,
        ]

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if json_format:
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
    else:
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(
                colors=True,
                pad_event=40,
            ),
            foreign_pre_chain=shared_processors,
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = []  
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    for _log in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]:
        _logger = logging.getLogger(_log)
        _logger.handlers = []
        _logger.propagate = True

    if not json_format:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("qdrant_client").setLevel(logging.WARNING)
        logging.getLogger("LiteLLM").setLevel(logging.WARNING)
        logging.getLogger("litellm").setLevel(logging.WARNING)
        logging.getLogger("instructor").setLevel(logging.WARNING)
        logging.getLogger("fastembed").setLevel(logging.WARNING)
        logging.getLogger("onnxruntime").setLevel(logging.WARNING)

    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)

def get_logger(name: str):
    return structlog.get_logger(name)
