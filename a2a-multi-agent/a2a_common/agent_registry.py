
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type, Union

import yaml
from pydantic import BaseModel, Field

from a2a_common.logging import get_logger

logger = get_logger(__name__)

class SlotConfig(BaseModel):
    description: Optional[str] = None
    required: bool = True
    type: str = "any"  
    artifact_hints: List[str] = Field(default_factory=list)
    default_artifact_key: Optional[str] = None

class AgentConfig(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    url: str

    input_slots: Dict[str, SlotConfig] = Field(default_factory=dict)
    output_slots: Dict[str, SlotConfig] = Field(default_factory=dict)

    tags: List[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return self.id

class AgentRegistry:
    def __init__(self, yaml_path: Union[str, Path]) -> None:
        self._path = Path(yaml_path)
        self._agents: Dict[str, AgentConfig] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Agent-Registry YAML nicht gefunden: {self._path}"
            )

        raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        agents_cfg = raw.get("agents", {})

        self._agents = {}
        for key, cfg in agents_cfg.items():
            cfg = dict(cfg or {})
            cfg.setdefault("id", key)

            try:
                agent = AgentConfig(**cfg)
                self._agents[key] = agent
            except Exception as exc:  
                logger.error(
                    "Fehler beim Laden von Agent '%s' aus Registry %s: %s",
                    key,
                    self._path,
                    exc,
                )

    def get(self, key: str) -> AgentConfig:
        try:
            return self._agents[key]
        except KeyError:
            raise KeyError(
                f"Agent '{key}' nicht in Registry {self._path} gefunden."
            )

    def getAllAgents(self) -> Dict[str, AgentConfig]:
        return self._agents

    def is_slot_required(self, agent_id: str, slot_name: str) -> bool:
        try:
            agent_config = self.get(agent_id)
            slot_config = agent_config.input_slots.get(slot_name)
            if slot_config:
                return slot_config.required
        except KeyError:
            return False  
        return False 

    def get_input_schema(self, agent_id: str) -> Optional[Type[BaseModel]]:
        from a2a_common.schemas import AGENT_SCHEMAS
        schemas = AGENT_SCHEMAS.get(agent_id)
        return schemas[0] if schemas else None

    def get_output_schema(self, agent_id: str) -> Optional[Type[BaseModel]]:
        from a2a_common.schemas import AGENT_SCHEMAS
        schemas = AGENT_SCHEMAS.get(agent_id)
        return schemas[1] if schemas else None

    def get_schemas(self, agent_id: str) -> Optional[Tuple[Type[BaseModel], Type[BaseModel]]]:
        from a2a_common.schemas import AGENT_SCHEMAS
        return AGENT_SCHEMAS.get(agent_id)

    def list_agents_with_schemas(self) -> List[str]:
        from a2a_common.schemas import AGENT_SCHEMAS
        return [aid for aid in self._agents.keys() if aid in AGENT_SCHEMAS]

    @property
    def rag(self) -> AgentConfig:
        return self.get("agent_rag")

    @property
    def summarizer(self) -> AgentConfig:
        return self.get("agent_summarizer")

    @property
    def guard(self) -> AgentConfig:
        return self.get("agent_guard")