"""
Version service for managing versioned artifacts.

Provides a unified interface for version operations across
prompts, agents, and skills (DB-02 rollback capability).
"""
from typing import Optional, List, Literal, Union

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.versioned_models import Prompt, Agent, Skill
from app.repositories.version_repository import VersionRepository

# Supported artifact types
ArtifactType = Literal["prompt", "agent", "skill"]

# Type alias for any versioned model
VersionedModel = Union[Prompt, Agent, Skill]

# Mapping from artifact type string to model class
MODEL_MAP: dict[ArtifactType, type] = {
    "prompt": Prompt,
    "agent": Agent,
    "skill": Skill,
}


class VersionService:
    """
    Service for version management across all versioned artifacts.

    Implements DB-02 (rollback capability) by providing:
    - Version history retrieval
    - Version counting
    - Rollback to previous versions
    - Version comparison

    Usage:
        async with get_session() as session:
            service = VersionService(session)
            history = await service.get_version_history("prompt", prompt_id)
            rolled_back = await service.rollback("prompt", prompt_id, 0)
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize the version service.

        Args:
            session: AsyncSession for database operations
        """
        self.session = session
        self._repositories: dict[ArtifactType, VersionRepository] = {}

    def _get_repository(self, artifact_type: ArtifactType) -> VersionRepository:
        """
        Get or create a repository for the given artifact type.

        Args:
            artifact_type: One of "prompt", "agent", "skill"

        Returns:
            VersionRepository configured for the artifact type

        Raises:
            ValueError: If artifact_type is not recognized
        """
        if artifact_type not in MODEL_MAP:
            raise ValueError(
                f"Unknown artifact type: {artifact_type}. "
                f"Must be one of: {list(MODEL_MAP.keys())}"
            )

        if artifact_type not in self._repositories:
            model_class = MODEL_MAP[artifact_type]
            self._repositories[artifact_type] = VersionRepository(
                session=self.session,
                model_class=model_class,
            )

        return self._repositories[artifact_type]

    async def get_version_history(
        self, artifact_type: ArtifactType, artifact_id: str
    ) -> List[dict]:
        """
        Get the complete version history for an artifact.

        Args:
            artifact_type: Type of artifact ("prompt", "agent", "skill")
            artifact_id: UUID string of the artifact

        Returns:
            List of version entries, newest first, each containing:
                - version_index: 0-based version number
                - transaction_id: Database transaction ID
                - operation_type: Type of change
                - data: Snapshot of artifact at that version
        """
        repo = self._get_repository(artifact_type)
        return await repo.get_version_history(artifact_id)

    async def get_version_count(
        self, artifact_type: ArtifactType, artifact_id: str
    ) -> int:
        """
        Get the number of versions for an artifact.

        Args:
            artifact_type: Type of artifact ("prompt", "agent", "skill")
            artifact_id: UUID string of the artifact

        Returns:
            Number of versions (0 if artifact doesn't exist)
        """
        history = await self.get_version_history(artifact_type, artifact_id)
        return len(history)

    async def rollback(
        self,
        artifact_type: ArtifactType,
        artifact_id: str,
        version_index: int,
    ) -> Optional[VersionedModel]:
        """
        Rollback an artifact to a previous version.

        This creates a new version with the old state (preserves history).
        The artifact's current state becomes a copy of the specified version.

        Args:
            artifact_type: Type of artifact ("prompt", "agent", "skill")
            artifact_id: UUID string of the artifact
            version_index: 0-based version index to rollback to

        Returns:
            The updated artifact if successful, None if not found

        Raises:
            ValueError: If version_index is negative or artifact type unknown
        """
        if version_index < 0:
            raise ValueError("version_index must be non-negative")

        repo = self._get_repository(artifact_type)
        return await repo.rollback_to_version(artifact_id, version_index)

    async def compare_versions(
        self,
        artifact_type: ArtifactType,
        artifact_id: str,
        version_a: int,
        version_b: int,
    ) -> dict:
        """
        Compare two versions of an artifact.

        Args:
            artifact_type: Type of artifact ("prompt", "agent", "skill")
            artifact_id: UUID string of the artifact
            version_a: First version index to compare
            version_b: Second version index to compare

        Returns:
            Dictionary containing:
                - version_a: Data from first version
                - version_b: Data from second version
                - changed_fields: List of field names that differ
                - changes: Dict mapping field name to (old_value, new_value)

        Raises:
            ValueError: If either version doesn't exist
        """
        repo = self._get_repository(artifact_type)

        data_a = await repo.get_version_at(artifact_id, version_a)
        data_b = await repo.get_version_at(artifact_id, version_b)

        if data_a is None:
            raise ValueError(f"Version {version_a} not found for {artifact_type} {artifact_id}")
        if data_b is None:
            raise ValueError(f"Version {version_b} not found for {artifact_type} {artifact_id}")

        # Find changed fields
        all_keys = set(data_a.keys()) | set(data_b.keys())
        changed_fields = []
        changes = {}

        for key in all_keys:
            val_a = data_a.get(key)
            val_b = data_b.get(key)
            if val_a != val_b:
                changed_fields.append(key)
                changes[key] = (val_a, val_b)

        return {
            'version_a': data_a,
            'version_b': data_b,
            'changed_fields': sorted(changed_fields),
            'changes': changes,
        }

    async def get_artifact(
        self, artifact_type: ArtifactType, artifact_id: str
    ) -> Optional[VersionedModel]:
        """
        Get the current version of an artifact.

        Args:
            artifact_type: Type of artifact ("prompt", "agent", "skill")
            artifact_id: UUID string of the artifact

        Returns:
            The artifact if found, None otherwise
        """
        repo = self._get_repository(artifact_type)
        return await repo.get_by_id(artifact_id)
