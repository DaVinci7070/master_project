import logging
from typing import Any, Optional

from pydantic import create_model, Field, ValidationError

logger = logging.getLogger(__name__)


class ArtifactSchemaValidator:
    """
    Runtime schema validator for artifact payloads.

    Uses Pydantic create_model() for dynamic validation.
    Validates at write time (fail fast per CONTEXT).
    """

    def __init__(self):
        """Initialize validator with schema cache."""
        self._schema_cache: dict[str, type] = {}

    def register_schema(
        self,
        artifact_type: str,
        schema: dict[str, Any]
    ) -> None:
        """
        Register a schema for an artifact type.

        Args:
            artifact_type: Type identifier
            schema: Dict mapping field names to (type, Field) tuples
                   Example: {"score": (float, Field(ge=0, le=1))}
        """
        model = create_model(
            f"Artifact_{artifact_type}",
            **schema
        )
        self._schema_cache[artifact_type] = model
        logger.debug(f"Registered schema for artifact type: {artifact_type}")

    def register_schema_from_json(
        self,
        artifact_type: str,
        json_schema: dict[str, Any]
    ) -> None:
        """
        Register a schema from JSON Schema format.

        Converts JSON Schema to Pydantic field definitions.
        Supports basic types: string, number, integer, boolean, array, object.
        """
        properties = json_schema.get("properties", {})
        required = set(json_schema.get("required", []))

        field_definitions = {}
        for field_name, field_schema in properties.items():
            field_type = self._json_schema_to_python_type(field_schema)
            is_required = field_name in required

            if is_required:
                field_definitions[field_name] = (field_type, ...)
            else:
                field_definitions[field_name] = (Optional[field_type], None)

        if field_definitions:
            self.register_schema(artifact_type, field_definitions)

    def _json_schema_to_python_type(self, schema: dict) -> type:
        """Convert JSON Schema type to Python type."""
        type_map = {
            "string": str,
            "number": float,
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        json_type = schema.get("type", "string")
        return type_map.get(json_type, Any)

    def validate(
        self,
        artifact_type: str,
        payload: dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate payload against registered schema.

        Args:
            artifact_type: Type identifier
            payload: Data to validate

        Returns:
            (is_valid, error_message)
        """
        if artifact_type not in self._schema_cache:
            logger.debug(f"No schema registered for {artifact_type}, skipping validation")
            return True, None

        model = self._schema_cache[artifact_type]
        try:
            model(**payload)
            return True, None
        except ValidationError as e:
            error_msg = str(e)
            logger.warning(f"Artifact validation failed for {artifact_type}: {error_msg}")
            return False, error_msg

    def has_schema(self, artifact_type: str) -> bool:
        """Check if schema is registered for artifact type."""
        return artifact_type in self._schema_cache

    def get_registered_types(self) -> list[str]:
        """Get list of artifact types with registered schemas."""
        return list(self._schema_cache.keys())

    def clear(self) -> None:
        """Clear all registered schemas (for testing)."""
        self._schema_cache.clear()
