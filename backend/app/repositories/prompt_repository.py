"""
Prompt repository for database operations.

Provides CRUD operations for prompt storage and retrieval.
"""
import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.versioned_models import Prompt

log = logging.getLogger(__name__)


class PromptRepository:
    """
    Repository for prompt database operations.

    Handles persistence of prompt records with version tracking
    via SQLAlchemy-Continuum.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize prompt repository.

        Args:
            session: AsyncSession for database operations
        """
        self.session = session
        self.log = log

    async def create(
        self,
        name: str,
        content: str,
        parent_id: Optional[str] = None,
        prompt_metadata: Optional[dict] = None
    ) -> Prompt:
        """
        Create a new prompt record.

        Args:
            name: Name of the prompt
            content: Prompt content/template
            parent_id: Optional parent prompt ID for versioning
            prompt_metadata: Optional metadata dictionary

        Returns:
            Created Prompt instance
        """
        log.info(f"Creating prompt: {name}")

        prompt = Prompt(
            name=name,
            content=content,
            parent_id=parent_id,
            prompt_metadata=prompt_metadata or {},
            is_active=True,
        )

        self.session.add(prompt)
        await self.session.flush()
        await self.session.refresh(prompt)

        log.info(f"Created prompt id={prompt.id}, name={prompt.name}")
        return prompt

    async def get_by_id(self, prompt_id: str) -> Optional[Prompt]:
        """
        Get a prompt by its ID.

        Args:
            prompt_id: UUID string of the prompt

        Returns:
            Prompt if found, None otherwise
        """
        log.debug(f"Getting prompt by id={prompt_id}")
        stmt = select(Prompt).where(Prompt.id == prompt_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[Prompt]:
        """
        Get an active prompt by its name.

        Returns the most recent active prompt with that name.

        Args:
            name: Name of the prompt

        Returns:
            Prompt if found, None otherwise
        """
        log.debug(f"Getting prompt by name={name}")
        stmt = select(Prompt).where(
            Prompt.name == name,
            Prompt.is_active == True
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> List[Prompt]:
        """
        List all active prompts.

        Returns:
            List of active Prompt instances ordered by name
        """
        log.debug("Listing active prompts")
        stmt = select(Prompt).where(Prompt.is_active == True).order_by(Prompt.name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, limit: int = 100, offset: int = 0) -> List[Prompt]:
        """
        List all prompts with pagination.

        Args:
            limit: Maximum number of prompts to return
            offset: Number of prompts to skip

        Returns:
            List of Prompt instances ordered by creation date
        """
        log.debug(f"Listing prompts limit={limit}, offset={offset}")
        stmt = (
            select(Prompt)
            .order_by(Prompt.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, prompt_id: str, **kwargs) -> Optional[Prompt]:
        """
        Update a prompt record.

        Args:
            prompt_id: UUID string of the prompt
            **kwargs: Fields to update (name, content, prompt_metadata, is_active)

        Returns:
            Updated Prompt if found, None otherwise
        """
        log.info(f"Updating prompt id={prompt_id}")

        prompt = await self.get_by_id(prompt_id)
        if not prompt:
            log.warning(f"Prompt not found for update: id={prompt_id}")
            return None

        # Update allowed fields
        allowed_fields = {"name", "content", "prompt_metadata", "is_active"}

        for key, value in kwargs.items():
            if key in allowed_fields and hasattr(prompt, key):
                setattr(prompt, key, value)

        await self.session.flush()
        await self.session.refresh(prompt)

        log.info(f"Updated prompt id={prompt_id}")
        return prompt

    async def set_active(self, prompt_id: str, is_active: bool) -> Optional[Prompt]:
        """
        Set the active status of a prompt.

        Args:
            prompt_id: UUID string of the prompt
            is_active: New active status

        Returns:
            Updated Prompt if found, None otherwise
        """
        log.info(f"Setting prompt id={prompt_id} is_active={is_active}")

        prompt = await self.get_by_id(prompt_id)
        if not prompt:
            log.warning(f"Prompt not found: id={prompt_id}")
            return None

        prompt.is_active = is_active
        await self.session.flush()
        await self.session.refresh(prompt)

        return prompt

    async def get_children(self, prompt_id: str) -> List[Prompt]:
        """
        Get all child prompts of a given prompt.

        For tracking prompt evolution lineage.

        Args:
            prompt_id: UUID string of the parent prompt

        Returns:
            List of child Prompt instances ordered by creation date
        """
        log.debug(f"Getting children for prompt id={prompt_id}")
        stmt = select(Prompt).where(Prompt.parent_id == prompt_id).order_by(Prompt.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
