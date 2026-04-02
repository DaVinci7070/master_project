
import os
import json
from typing import Optional
from .artifacts import OrchestrationState
from a2a_common.logging import get_logger

logger = get_logger(__name__)

STORAGE_DIR = os.getenv("ORCHESTRATION_STORAGE_DIR", "/tmp/orchestration_states")

def ensure_storage():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR, exist_ok=True)

async def save_state(state: OrchestrationState):
    ensure_storage()
    file_path = os.path.join(STORAGE_DIR, f"{state.run_id}.json")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))
        logger.info(f"Orchestration State saved: {state.run_id}")
    except Exception as e:
        logger.error(f"Failed to save Orchestration State {state.run_id}: {e}")

async def load_state(run_id: str) -> Optional[OrchestrationState]:
    file_path = os.path.join(STORAGE_DIR, f"{run_id}.json")
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return OrchestrationState(**data)
    except Exception as e:
        logger.error(f"Failed to load Orchestration State {run_id}: {e}")
        return None
