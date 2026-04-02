"""Session-scoped artifact pool for inter-agent communication."""
import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone

from app.orchestration.artifacts.models import Artifact, AgentArtifactContract
from app.orchestration.artifacts.validators import ArtifactSchemaValidator

logger = logging.getLogger(__name__)


class ArtifactPool:
    """
    Session-only artifact store for inter-agent data passing.

    Key behaviors (per CONTEXT):
    - Session-only persistence: Discarded after execution run
    - Validate at write time: Fail fast, not at read time
    - Explicit declaration: Agents declare what they consume via contracts
    - Thread-safe: Uses asyncio.Lock for concurrent access

    NOT for long-term storage - use SharedMemory for that.
    """

    def __init__(
        self,
        execution_id: Optional[str] = None,
        validator: Optional[ArtifactSchemaValidator] = None
    ):
        """
        Initialize artifact pool.

        Args:
            execution_id: ID of the execution run (for correlation)
            validator: Schema validator (creates default if not provided)
        """
        self.execution_id = execution_id
        self.validator = validator or ArtifactSchemaValidator()

        self._artifacts: list[Artifact] = []
        self._by_type: dict[str, list[Artifact]] = {}
        self._lock = asyncio.Lock()

        # Registered agent contracts for pre-validation
        self._contracts: dict[str, AgentArtifactContract] = {}

    async def register_contract(self, contract: AgentArtifactContract) -> None:
        """
        Register an agent's artifact contract.

        Enables pre-validation of artifact flows.
        """
        async with self._lock:
            self._contracts[contract.agent_id] = contract

            # Register schemas from contract
            for decl in contract.declarations:
                if decl.payload_schema and decl.direction == "produces":
                    self.validator.register_schema_from_json(
                        decl.artifact_type,
                        decl.payload_schema
                    )

            logger.debug(f"Registered contract for agent: {contract.agent_id}")

    async def write(
        self,
        artifact: Artifact,
        validate: bool = True
    ) -> None:
        """
        Write artifact to pool with optional schema validation.

        Validates at write time (fail fast per CONTEXT).

        Args:
            artifact: The artifact to store
            validate: Whether to validate against schema (default True)

        Raises:
            ValueError: If validation fails
        """
        # Validate at write time (per CONTEXT decision)
        if validate:
            is_valid, error = self.validator.validate(
                artifact.artifact_type,
                artifact.payload
            )
            if not is_valid:
                raise ValueError(
                    f"Artifact validation failed for {artifact.artifact_type}: {error}"
                )

        async with self._lock:
            # Add execution_id if not set
            if artifact.execution_id is None and self.execution_id:
                # Create new artifact with execution_id (immutable model)
                artifact = Artifact(
                    artifact_type=artifact.artifact_type,
                    payload=artifact.payload,
                    source_agent_id=artifact.source_agent_id,
                    timestamp=artifact.timestamp,
                    execution_id=self.execution_id,
                    correlation_id=artifact.correlation_id
                )

            self._artifacts.append(artifact)
            self._by_type.setdefault(artifact.artifact_type, []).append(artifact)

            logger.debug(
                f"Artifact written: type={artifact.artifact_type}, "
                f"source={artifact.source_agent_id}"
            )

    async def read(
        self,
        artifact_types: list[str],
        source_agent_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> list[Artifact]:
        """
        Read artifacts by type declaration.

        Per CONTEXT: Agents explicitly declare which types they consume.

        Args:
            artifact_types: List of artifact types to retrieve
            source_agent_id: Filter by source agent (optional)
            limit: Max artifacts to return (optional)

        Returns:
            List of matching artifacts, newest first
        """
        async with self._lock:
            results = []
            for atype in artifact_types:
                artifacts = self._by_type.get(atype, [])
                for artifact in artifacts:
                    if source_agent_id and artifact.source_agent_id != source_agent_id:
                        continue
                    results.append(artifact)

            # Sort by timestamp (newest first)
            results.sort(key=lambda a: a.timestamp, reverse=True)

            if limit:
                results = results[:limit]

            return results

    async def read_for_agent(
        self,
        agent_id: str,
        limit: Optional[int] = None
    ) -> list[Artifact]:
        """
        Read artifacts that an agent declared it consumes.

        Uses registered contract to filter by declared types.

        Args:
            agent_id: Agent requesting artifacts
            limit: Max artifacts to return

        Returns:
            Artifacts matching agent's declared consumes types
        """
        contract = self._contracts.get(agent_id)
        if not contract:
            logger.warning(f"No contract registered for agent: {agent_id}")
            return []

        consumes = contract.consumes()
        return await self.read(consumes, limit=limit)

    async def clear(self) -> None:
        """
        Discard all artifacts (end of execution run).

        Per CONTEXT: Session-only persistence.
        """
        async with self._lock:
            count = len(self._artifacts)
            self._artifacts.clear()
            self._by_type.clear()
            logger.info(f"Artifact pool cleared: {count} artifacts discarded")

    async def count(self) -> int:
        """Get total artifact count."""
        async with self._lock:
            return len(self._artifacts)

    async def count_by_type(self) -> dict[str, int]:
        """Get artifact counts by type."""
        async with self._lock:
            return {atype: len(arts) for atype, arts in self._by_type.items()}

    async def get_all_types(self) -> list[str]:
        """Get list of artifact types in pool."""
        async with self._lock:
            return list(self._by_type.keys())

    def validate_flow(
        self,
        producer_id: str,
        consumer_id: str,
        artifact_type: str
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that producer produces and consumer consumes the artifact type.

        Pre-validation for artifact flows.

        Returns:
            (is_valid, error_message)
        """
        producer_contract = self._contracts.get(producer_id)
        consumer_contract = self._contracts.get(consumer_id)

        if not producer_contract:
            return False, f"Producer {producer_id} has no registered contract"
        if not consumer_contract:
            return False, f"Consumer {consumer_id} has no registered contract"

        if artifact_type not in producer_contract.produces():
            return False, f"Producer {producer_id} does not produce {artifact_type}"
        if artifact_type not in consumer_contract.consumes():
            return False, f"Consumer {consumer_id} does not consume {artifact_type}"

        return True, None
