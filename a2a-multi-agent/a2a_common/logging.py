
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

def _get_log_level_from_env() -> int:
    level_name = "INFO"
    return getattr(logging, level_name, logging.INFO)

def setup_logging(
    *,
    level: Optional[int] = None,
    include_uvicorn: bool = True,
) -> None:
    if level is None:
        level = _get_log_level_from_env()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    if include_uvicorn:
        _configure_uvicorn_loggers(formatter, level)

def _configure_uvicorn_loggers(formatter: logging.Formatter, level: int) -> None:
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.handlers.clear()
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
