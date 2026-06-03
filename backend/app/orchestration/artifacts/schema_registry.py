import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.sql.artifact_schema_models import ArtifactSchema
from app.orchestration.artifacts.validators import ArtifactSchemaValidator

logger = logging.getLogger(__name__)


class ArtifactSchemaRegistry:
    """
    Database-backed registry for artifact schemas.

    Loads schemas from database at runtime, enabling updates
    without code deployment (per CONTEXT decision).
    """

    def __init__(
        self,
        db: AsyncSession,
        validator: Optional[ArtifactSchemaValidator] = None
    ):
        """
        Initialize schema registry.

        Args:
            db: Database session
            validator: Validator to register schemas with
        """
        self.db = db
        self.validator = validator or ArtifactSchemaValidator()
        self._loaded = False
        self._schemas: dict[str, ArtifactSchema] = {}

    async def load_all(self, force_reload: bool = False) -> int:
        """
        Load all active schemas from database and register with validator.

        Args:
            force_reload: Force reload even if already loaded

        Returns:
            Number of schemas loaded
        """
        if self._loaded and not force_reload:
            logger.debug("Schemas already loaded, skipping")
            return len(self._schemas)

        result = await self.db.execute(
            select(ArtifactSchema).where(ArtifactSchema.is_active == True)
        )
        schemas = result.scalars().all()

        self.validator.clear()
        self._schemas.clear()

        for schema in schemas:
            self._register_schema(schema)

        self._loaded = True
        logger.info(f"Loaded {len(self._schemas)} artifact schemas from database")

        return len(self._schemas)

    def _register_schema(self, schema: ArtifactSchema) -> None:
        """Register a single schema with the validator."""
        try:
            self.validator.register_schema_from_json(
                artifact_type=schema.artifact_type,
                json_schema=schema.json_schema
            )
            self._schemas[schema.artifact_type] = schema
            logger.debug(f"Registered schema: {schema.artifact_type}")
        except Exception as e:
            logger.error(f"Failed to register schema {schema.artifact_type}: {e}")

    async def get_schema(self, artifact_type: str) -> Optional[ArtifactSchema]:
        """Get schema record by artifact type."""
        if not self._loaded:
            await self.load_all()

        if artifact_type in self._schemas:
            return self._schemas[artifact_type]

        result = await self.db.execute(
            select(ArtifactSchema).where(
                ArtifactSchema.artifact_type == artifact_type,
                ArtifactSchema.is_active == True
            )
        )
        schema = result.scalar_one_or_none()

        if schema:
            self._register_schema(schema)

        return schema

    async def create_schema(
        self,
        artifact_type: str,
        name: str,
        json_schema: dict,
        description: Optional[str] = None,
        example_payload: Optional[dict] = None,
        producing_agents: Optional[list[str]] = None,
        consuming_agents: Optional[list[str]] = None
    ) -> ArtifactSchema:
        """
        Create a new artifact schema in database.

        Args:
            artifact_type: Unique type identifier
            name: Human-readable name
            json_schema: JSON Schema definition
            description: Optional description
            example_payload: Optional example for documentation
            producing_agents: List of agent IDs that produce this type
            consuming_agents: List of agent IDs that consume this type

        Returns:
            Created ArtifactSchema
        """
        from uuid import uuid4

        schema = ArtifactSchema(
            id=str(uuid4()),
            artifact_type=artifact_type,
            name=name,
            json_schema=json_schema,
            description=description,
            example_payload=example_payload,
            producing_agents=producing_agents or [],
            consuming_agents=consuming_agents or []
        )

        self.db.add(schema)
        await self.db.commit()
        await self.db.refresh(schema)

        self._register_schema(schema)

        return schema

    async def update_schema(
        self,
        artifact_type: str,
        json_schema: dict,
        version: Optional[str] = None
    ) -> Optional[ArtifactSchema]:
        """
        Update an existing schema.

        Args:
            artifact_type: Type to update
            json_schema: New schema definition
            version: New version string

        Returns:
            Updated schema or None if not found
        """
        result = await self.db.execute(
            select(ArtifactSchema).where(
                ArtifactSchema.artifact_type == artifact_type
            )
        )
        schema = result.scalar_one_or_none()

        if not schema:
            logger.warning(f"Schema not found for update: {artifact_type}")
            return None

        schema.json_schema = json_schema
        if version:
            schema.version = version

        await self.db.commit()
        await self.db.refresh(schema)

        self._register_schema(schema)

        logger.info(f"Updated schema: {artifact_type} to version {schema.version}")
        return schema

    async def deactivate_schema(self, artifact_type: str) -> bool:
        """
        Deactivate a schema (soft delete).

        Returns:
            True if deactivated, False if not found
        """
        result = await self.db.execute(
            select(ArtifactSchema).where(
                ArtifactSchema.artifact_type == artifact_type
            )
        )
        schema = result.scalar_one_or_none()

        if not schema:
            return False

        schema.is_active = False
        await self.db.commit()

        self._schemas.pop(artifact_type, None)

        logger.info(f"Deactivated schema: {artifact_type}")
        return True

    def get_all_types(self) -> list[str]:
        """Get all registered artifact types."""
        return list(self._schemas.keys())

    def get_producers(self, artifact_type: str) -> list[str]:
        """Get agents that produce this artifact type."""
        schema = self._schemas.get(artifact_type)
        if schema:
            return schema.producing_agents or []
        return []

    def get_consumers(self, artifact_type: str) -> list[str]:
        """Get agents that consume this artifact type."""
        schema = self._schemas.get(artifact_type)
        if schema:
            return schema.consuming_agents or []
        return []

    def validate_artifact(
        self,
        artifact_type: str,
        payload: dict
    ) -> tuple[bool, Optional[str]]:
        """
        Validate artifact payload against registered schema.

        Returns:
            (is_valid, error_message)
        """
        return self.validator.validate(artifact_type, payload)


async def create_schema_registry(db: AsyncSession) -> ArtifactSchemaRegistry:
    """Factory function to create and initialize schema registry."""
    registry = ArtifactSchemaRegistry(db)
    await registry.load_all()
    return registry
