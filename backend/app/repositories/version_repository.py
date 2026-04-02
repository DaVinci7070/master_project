"""
Generic version repository for versioned models.

Provides version history, retrieval, and rollback operations
using SQLAlchemy-Continuum's version tracking.
"""
from typing import Generic, TypeVar, Optional, List, Any
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import class_mapper

T = TypeVar('T')


class VersionRepository(Generic[T]):
    """
    Generic repository for version operations on versioned models.

    Uses SQLAlchemy-Continuum's automatic version tracking to provide:
    - Version history retrieval
    - Point-in-time version access
    - Rollback to previous versions

    Type parameter T should be a versioned SQLAlchemy model
    (decorated with __versioned__ = {}).
    """

    def __init__(self, session: AsyncSession, model_class: type):
        """
        Initialize the version repository.

        Args:
            session: AsyncSession for database operations
            model_class: The versioned model class (e.g., Prompt, Agent, Skill)
        """
        self.session = session
        self.model_class = model_class
        self._version_class = None

    @property
    def version_class(self):
        """Get the Continuum version class for this model."""
        if self._version_class is None:
            # SQLAlchemy-Continuum adds a __versioned__ attribute with version_class
            self._version_class = self.model_class.__versioned__.get('class_')
            if self._version_class is None:
                # Fallback: Continuum names it <ModelName>Version
                version_class_name = f"{self.model_class.__name__}Version"
                # Get from mapper registry
                for mapper in class_mapper(self.model_class).registry.mappers:
                    if mapper.class_.__name__ == version_class_name:
                        self._version_class = mapper.class_
                        break
        return self._version_class

    async def get_by_id(self, entity_id: str) -> Optional[T]:
        """
        Get an entity by its ID.

        Args:
            entity_id: UUID string of the entity

        Returns:
            The entity if found, None otherwise
        """
        stmt = select(self.model_class).where(self.model_class.id == entity_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_version_history(self, entity_id: str) -> List[dict]:
        """
        Get the complete version history for an entity.

        Returns versions in descending order (newest first).

        Args:
            entity_id: UUID string of the entity

        Returns:
            List of version dictionaries containing:
                - version_index: The version number (0-based)
                - transaction_id: Continuum transaction ID
                - operation_type: 0=insert, 1=update, 2=delete
                - data: Snapshot of the entity at that version
        """
        version_cls = self.version_class
        if version_cls is None:
            return []

        # Get all versions for this entity, ordered by transaction_id descending
        stmt = (
            select(version_cls)
            .where(version_cls.id == entity_id)
            .order_by(desc(version_cls.transaction_id))
        )
        result = await self.session.execute(stmt)
        versions = result.scalars().all()

        history = []
        for idx, version in enumerate(reversed(versions)):
            # Convert version object to dict
            version_data = self._version_to_dict(version)
            history.append({
                'version_index': idx,
                'transaction_id': version.transaction_id,
                'operation_type': getattr(version, 'operation_type', None),
                'data': version_data,
            })

        # Reverse to return newest first
        return list(reversed(history))

    async def get_version_at(self, entity_id: str, version_index: int) -> Optional[dict]:
        """
        Get the entity state at a specific version.

        Args:
            entity_id: UUID string of the entity
            version_index: 0-based version index (0 is the first version)

        Returns:
            Dictionary of entity state at that version, or None if not found
        """
        history = await self.get_version_history(entity_id)

        # Find the version by index (history is newest-first, so reverse to find)
        for version_entry in history:
            if version_entry['version_index'] == version_index:
                return version_entry['data']

        return None

    async def rollback_to_version(
        self, entity_id: str, version_index: int
    ) -> Optional[T]:
        """
        Rollback an entity to a previous version.

        This creates a NEW version with the old state (doesn't delete history).
        The entity's current state becomes a copy of the specified version.

        Args:
            entity_id: UUID string of the entity
            version_index: 0-based version index to rollback to

        Returns:
            The updated entity if successful, None if entity or version not found
        """
        # Get current entity
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return None

        # Get the target version data
        version_data = await self.get_version_at(entity_id, version_index)
        if version_data is None:
            return None

        # Apply version data to entity (excluding id, created_at, and relationships)
        exclude_fields = {'id', 'created_at', 'transaction_id', 'operation_type'}
        for key, value in version_data.items():
            if key not in exclude_fields and hasattr(entity, key):
                setattr(entity, key, value)

        # Flush to trigger Continuum to create a new version
        await self.session.flush()

        return entity

    def _version_to_dict(self, version: Any) -> dict:
        """
        Convert a version object to a dictionary.

        Args:
            version: SQLAlchemy-Continuum version object

        Returns:
            Dictionary representation of the version
        """
        result = {}
        # Get column names from the version class
        mapper = class_mapper(version.__class__)
        for column in mapper.columns:
            key = column.key
            # Skip Continuum internal columns
            if key in ('transaction_id', 'end_transaction_id', 'operation_type'):
                continue
            value = getattr(version, key, None)
            result[key] = value
        return result
