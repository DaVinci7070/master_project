from __future__ import annotations

from typing import Any, Dict, Optional, Type, List
from pydantic import BaseModel, ValidationError

from a2a_common.logging import get_logger
from a2a_common.agent_registry import AgentRegistry, AgentConfig

logger = get_logger(__name__)

class PackageBuildError(Exception):
    def __init__(self, agent_id: str, message: str, missing_fields: Optional[List[str]] = None):
        self.agent_id = agent_id
        self.missing_fields = missing_fields or []
        super().__init__(f"Failed to build package for {agent_id}: {message}")

class AgentPackageBuilder:

    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def build_package(
        self,
        agent_id: str,
        artifacts: Dict[str, Any],
        input_mapping: Optional[Dict[str, str]] = None,
    ) -> BaseModel:
        input_schema = self.registry.get_input_schema(agent_id)
        if input_schema is None:
            raise PackageBuildError(
                agent_id,
                f"No input schema defined for agent '{agent_id}'"
            )

        agent_config = self.registry.get(agent_id)

        data: Dict[str, Any] = {}
        missing_required: List[str] = []

        schema_fields = input_schema.model_fields

        for field_name, field_info in schema_fields.items():
            value = self._resolve_field_value(
                field_name=field_name,
                field_info=field_info,
                agent_config=agent_config,
                artifacts=artifacts,
                input_mapping=input_mapping,
            )

            if value is not None:
                data[field_name] = value
            elif field_info.is_required():
                missing_required.append(field_name)

        if missing_required:
            raise PackageBuildError(
                agent_id,
                f"Missing required fields: {missing_required}",
                missing_fields=missing_required,
            )

        try:
            return input_schema.model_validate(data)
        except ValidationError as e:
            raise PackageBuildError(
                agent_id,
                f"Validation failed: {e}",
            ) from e

    def _resolve_field_value(
        self,
        field_name: str,
        field_info: Any,
        agent_config: AgentConfig,
        artifacts: Dict[str, Any],
        input_mapping: Optional[Dict[str, str]],
    ) -> Any:
        if input_mapping and field_name in input_mapping:
            artifact_key = input_mapping[field_name]
            if artifact_key in artifacts:
                return artifacts[artifact_key]

        slot_config = agent_config.input_slots.get(field_name)
        if slot_config:
            for hint in slot_config.artifact_hints:
                if hint in artifacts:
                    return artifacts[hint]
            if slot_config.default_artifact_key and slot_config.default_artifact_key in artifacts:
                return artifacts[slot_config.default_artifact_key]

        if field_name in artifacts:
            return artifacts[field_name]

        semantic_mappings = {
            "transcript": ["original_transcript", "normalized_transcript", "transcript"],
            "report": ["final_report", "summary_report", "report"],
            "template_result": ["template_result", "template_selection"],
            "context_documents": ["context_documents", "rag_context"],
            "user_id": ["user_id"],
        }

        if field_name in semantic_mappings:
            for candidate in semantic_mappings[field_name]:
                if candidate in artifacts:
                    return artifacts[candidate]

        return None

    def get_required_artifacts(self, agent_id: str) -> List[str]:
        input_schema = self.registry.get_input_schema(agent_id)
        if input_schema is None:
            return []

        agent_config = self.registry.get(agent_id)
        required = []

        for field_name, field_info in input_schema.model_fields.items():
            if field_info.is_required():
                slot_config = agent_config.input_slots.get(field_name)
                if slot_config and slot_config.artifact_hints:
                    required.extend(slot_config.artifact_hints)
                else:
                    required.append(field_name)

        return list(set(required))

def build_agent_package(
    registry: AgentRegistry,
    agent_id: str,
    artifacts: Dict[str, Any],
    input_mapping: Optional[Dict[str, str]] = None,
) -> BaseModel:
    builder = AgentPackageBuilder(registry)
    return builder.build_package(agent_id, artifacts, input_mapping)
