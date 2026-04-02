
from __future__ import annotations

import os
from pathlib import Path

from a2a_common.config import (
    ORCHESTRATOR_PORT as GLOBAL_ORCHESTRATOR_PORT,
    ROOT_DIR,
    get_agent_registry_path,
)

ORCHESTRATOR_HOST: str = os.getenv("ORCHESTRATOR_HOST", "0.0.0.0")

ORCHESTRATOR_PORT: int = int(
    os.getenv("ORCHESTRATOR_PORT", str(GLOBAL_ORCHESTRATOR_PORT))
)

DEFAULT_AGENT_REGISTRY_PATH: Path = ROOT_DIR / "agents" / "agents_registry.yaml"

AGENT_REGISTRY_PATH: Path = Path(
    os.getenv(
        "AGENT_REGISTRY_PATH",
        str(DEFAULT_AGENT_REGISTRY_PATH),
    )
)

def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

ORCH_USE_GUARD_INPUT: bool = _env_flag("ORCH_USE_GUARD_INPUT", True)

ORCH_USE_RAG: bool = _env_flag("ORCH_USE_RAG", True)

ORCH_USE_SUMMARIZER: bool = _env_flag("ORCH_USE_SUMMARIZER", True)

ORCH_USE_GUARD_OUTPUT: bool = _env_flag("ORCH_USE_GUARD_OUTPUT", True)

def get_listen_address() -> tuple[str, int]:
    return ORCHESTRATOR_HOST, ORCHESTRATOR_PORT

def get_registry_path() -> Path:
    global_default = get_agent_registry_path()
    if os.getenv("AGENT_REGISTRY_PATH") is None:
        return global_default
    return AGENT_REGISTRY_PATH
