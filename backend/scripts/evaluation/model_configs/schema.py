from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini/gemini-2.0-flash": {
        "input": 0.10,
        "output": 0.40,
        "thinking": 0.0,
    },
    "gemini/gemini-2.5-flash": {
        "input": 0.15,
        "output": 0.60,
        "thinking": 0.35,
    },
    "gemini/gemini-3.5-flash": {
        "input": 0.15,
        "output": 0.60,
        "thinking": 0.35,
    },
}

VALID_TASK_TYPES = {
    "research", "architecture", "implementation",
    "review", "code_fix", "semantic_validation", "general",
}

VALID_LEVELS = {"L1", "L2", "L3", "L4", "L5"}


class AblationFlags(BaseModel):
    autonomous_evolution_enabled: bool = True
    shared_memory_enabled: bool = True
    skill_reuse_enabled: bool = True


class ModelConfig(BaseModel):
    config_id: str
    description: str
    levels: list[str] = Field(default_factory=lambda: ["L1", "L2", "L3", "L4", "L5"])
    seeds: int = Field(default=3, ge=1, le=10)
    mode: Literal["cold", "warm"] = "cold"
    judge_model: str = "gemini/gemini-3.5-flash"
    models: dict[str, str]
    ablation: AblationFlags = Field(default_factory=AblationFlags)

    @model_validator(mode="after")
    def validate_task_types(self) -> "ModelConfig":
        unknown = set(self.models.keys()) - VALID_TASK_TYPES
        if unknown:
            raise ValueError(f"Unbekannte Task-Types: {unknown}")
        missing = VALID_TASK_TYPES - set(self.models.keys())
        if missing:
            raise ValueError(f"Fehlende Task-Types: {missing}")
        return self

    @model_validator(mode="after")
    def validate_levels(self) -> "ModelConfig":
        invalid = set(self.levels) - VALID_LEVELS
        if invalid:
            raise ValueError(f"Ungültige Levels: {invalid}")
        return self

    def is_uniform(self) -> bool:
        """Prüft ob alle Rollen dasselbe Modell nutzen."""
        models = set(self.models.values())
        return len(models) == 1

    def primary_model(self) -> str:
        """Gibt das (häufigste) Modell zurück."""
        from collections import Counter
        counts = Counter(self.models.values())
        return counts.most_common(1)[0][0]

    def estimate_cost_per_task(self, avg_input_tokens: int = 2000, avg_output_tokens: int = 500) -> float:
        """Grobe Kostenschätzung pro Task basierend auf dem primären Modell."""
        model = self.primary_model()
        pricing = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0, "thinking": 0.0})
        input_cost = (avg_input_tokens / 1_000_000) * pricing["input"]
        output_cost = (avg_output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost


def load_model_config(name_or_path: str) -> ModelConfig:
    """
    Lädt eine ModelConfig aus YAML.

    Args:
        name_or_path: Config-Name (z.B. 'u_weak_full') oder voller Pfad.
                      Bei Namen wird in model_configs/ gesucht.
    """
    path = Path(name_or_path)
    if not path.suffix:
        configs_dir = Path(__file__).parent
        path = configs_dir / f"{name_or_path}.yaml"

    if not path.exists():
        raise FileNotFoundError(f"Config nicht gefunden: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    return ModelConfig(**data)


def list_model_configs() -> list[dict[str, str]]:
    """Listet alle verfügbaren Config-Dateien."""
    configs_dir = Path(__file__).parent
    result = []
    for yaml_file in sorted(configs_dir.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        result.append({
            "name": yaml_file.stem,
            "config_id": data.get("config_id", yaml_file.stem),
            "description": data.get("description", ""),
        })
    return result
