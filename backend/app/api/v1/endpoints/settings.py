from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm_router import get_router, TaskType

router = APIRouter(prefix="/settings", tags=["settings"])
log = logging.getLogger(__name__)


class ModelsUpdateRequest(BaseModel):
    models: dict[str, str] = Field(
        ...,
        description="Mapping task_type → model_id",
        json_schema_extra={"example": {
            "research": "gemini/gemini-2.5-flash",
            "architecture": "gemini/gemini-2.5-flash",
            "implementation": "gemini/gemini-2.5-flash",
            "review": "gemini/gemini-2.5-flash",
            "code_fix": "gemini/gemini-2.5-flash",
            "semantic_validation": "gemini/gemini-2.5-flash",
            "general": "gemini/gemini-2.5-flash",
        }},
    )


class AblationUpdateRequest(BaseModel):
    autonomous_evolution_enabled: bool | None = None
    shared_memory_enabled: bool | None = None
    skill_reuse_enabled: bool | None = None


class CurrentSettingsResponse(BaseModel):
    models: dict[str, str]
    ablation: dict[str, bool]


class ModelsUpdateResponse(BaseModel):
    previous: dict[str, str]
    current: dict[str, str]


class AblationUpdateResponse(BaseModel):
    previous: dict[str, bool]
    current: dict[str, bool]


@router.get("/current", response_model=CurrentSettingsResponse)
async def get_current_settings():
    """Gibt die aktuellen Modell-Zuordnungen und Ablation-Flags zurück."""
    llm_router = get_router()
    return CurrentSettingsResponse(
        models=llm_router.get_all_models(),
        ablation=_get_ablation_flags(),
    )


@router.put("/models", response_model=ModelsUpdateResponse)
async def update_models(request: ModelsUpdateRequest):
    """Setzt alle LLM-Rollen auf die angegebenen Modelle."""
    llm_router = get_router()
    previous = llm_router.bulk_update(request.models)
    current = llm_router.get_all_models()
    log.info("Models updated via API: %s", current)
    return ModelsUpdateResponse(previous=previous, current=current)


@router.put("/ablation", response_model=AblationUpdateResponse)
async def update_ablation(request: AblationUpdateRequest):
    """Setzt Ablation-Feature-Flags zur Laufzeit."""
    previous = _get_ablation_flags()

    if request.autonomous_evolution_enabled is not None:
        settings.autonomous_evolution_enabled = request.autonomous_evolution_enabled
    if request.shared_memory_enabled is not None:
        settings.shared_memory_enabled = request.shared_memory_enabled
    if request.skill_reuse_enabled is not None:
        settings.skill_reuse_enabled = request.skill_reuse_enabled

    current = _get_ablation_flags()
    log.info("Ablation flags updated via API: %s", current)
    return AblationUpdateResponse(previous=previous, current=current)


def _get_ablation_flags() -> dict[str, bool]:
    return {
        "autonomous_evolution_enabled": settings.autonomous_evolution_enabled,
        "shared_memory_enabled": settings.shared_memory_enabled,
        "skill_reuse_enabled": settings.skill_reuse_enabled,
    }
