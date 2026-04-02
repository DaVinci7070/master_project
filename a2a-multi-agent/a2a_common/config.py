
from __future__ import annotations

import os
from pathlib import Path

THIS_FILE = Path(__file__).resolve()

ROOT_DIR = THIS_FILE.parents[1]

CONFIG_DIR = ROOT_DIR / "config"

AGENT_REGISTRY_PATH: Path = Path(
    os.getenv(
        "AGENT_REGISTRY_PATH",
        CONFIG_DIR / "agents_registry.yaml",
    )
)

DEFAULT_HOST = os.getenv("AGENT_HOST", "0.0.0.0")

ORCHESTRATOR_PORT: int = int(os.getenv("ORCHESTRATOR_PORT", "8000"))
SUMMARIZER_PORT: int = int(os.getenv("SUMMARIZER_PORT", "8001"))
RAG_PORT: int = int(os.getenv("RAG_PORT", "8004"))
GUARD_PORT: int = int(os.getenv("GUARD_PORT", "8005"))
TEMPLATE_PORT: int = int(os.getenv("TEMPLATE_PORT", "8006"))
DEFECT_PORT: int = int(os.getenv("DEFECT_PORT", "8008"))
SAFETY_PORT: int = int(os.getenv("SAFETY_PORT", "8009"))
CLAIM_PORT: int = int(os.getenv("CLAIM_PORT", "8010"))
QUALITY_PORT: int = int(os.getenv("QUALITY_PORT", "8011"))

ORCHESTRATOR_URL: str = os.getenv(
    "ORCHESTRATOR_URL", f"http://orchestrator:{ORCHESTRATOR_PORT}"
)
SUMMARIZER_URL: str = os.getenv(
    "SUMMARIZER_URL", f"http://summarizer:{SUMMARIZER_PORT}"
)
RAG_URL: str = os.getenv(
    "RAG_URL", f"http://rag:{RAG_PORT}"
)
GUARD_URL: str = os.getenv(
    "GUARD_URL", f"http://guard:{GUARD_PORT}"
)
TEMPLATE_URL: str = os.getenv(
    "TEMPLATE_URL", f"http://template:{TEMPLATE_PORT}"
)
DEFECT_URL: str = os.getenv(
    "DEFECT_URL", f"http://defect:{DEFECT_PORT}"
)
SAFETY_URL: str = os.getenv(
    "SAFETY_URL", f"http://safety:{SAFETY_PORT}"
)
CLAIM_URL: str = os.getenv(
    "CLAIM_URL", f"http://claim:{CLAIM_PORT}"
)
QUALITY_URL: str = os.getenv(
    "QUALITY_URL", f"http://quality:{QUALITY_PORT}"
)

def get_agent_registry_path() -> Path:
    return AGENT_REGISTRY_PATH

def debug_print_config() -> None:
    print("BACKEND_DIR          =", ROOT_DIR)
    print("AGENT_REGISTRY_PATH  =", AGENT_REGISTRY_PATH)
    print("ORCHESTRATOR_PORT    =", ORCHESTRATOR_PORT)
    print("SUMMARIZER_PORT      =", SUMMARIZER_PORT)
    print("RAG_PORT             =", RAG_PORT)
    print("GUARD_PORT           =", GUARD_PORT)
    print("TEMPLATE_PORT        =", TEMPLATE_PORT)
    print("DEFECT_PORT          =", DEFECT_PORT)
    print("SAFETY_PORT          =", SAFETY_PORT)
    print("CLAIM_PORT           =", CLAIM_PORT)
    print("QUALITY_PORT         =", QUALITY_PORT)

