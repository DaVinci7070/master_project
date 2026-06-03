import logging
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.versioned_models import Skill

log = logging.getLogger(__name__)


class SkillRepository:
    """
    Repository for skill database operations.

    Handles persistence of skill records with version tracking
    via SQLAlchemy-Continuum.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize skill repository.

        Args:
            session: AsyncSession for database operations
        """
        self.session = session

    async def create(self, skill_data: dict) -> Skill:
        """
        Create a new skill record.

        Args:
            skill_data: Dictionary containing skill attributes

        Returns:
            Created Skill instance
        """
        log.info(f"Creating skill: {skill_data.get('name', 'unnamed')}")

        skill = Skill(
            name=skill_data["name"],
            description=skill_data.get("description"),
            code=skill_data["code"],
            test_cases=skill_data.get("test_cases", []),
            skill_metadata=skill_data.get("skill_metadata", {}),
            is_active=skill_data.get("is_active", False),
            parent_id=skill_data.get("parent_id"),
        )

        self.session.add(skill)
        await self.session.flush()
        await self.session.refresh(skill)

        log.info(f"Created skill id={skill.id}, name={skill.name}")
        return skill

    async def get_by_id(self, skill_id: str) -> Optional[Skill]:
        """
        Get a skill by its ID.

        Args:
            skill_id: UUID string of the skill

        Returns:
            Skill if found, None otherwise
        """
        log.debug(f"Getting skill by id={skill_id}")
        stmt = select(Skill).where(Skill.id == skill_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[Skill]:
        """
        Get a skill by its name.

        Args:
            name: Name of the skill

        Returns:
            Skill if found, None otherwise
        """
        log.debug(f"Getting skill by name={name}")
        stmt = select(Skill).where(Skill.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> List[Skill]:
        """
        List all active skills.

        Returns:
            List of active Skill instances
        """
        log.debug("Listing active skills")
        stmt = select(Skill).where(Skill.is_active == True).order_by(Skill.name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, limit: int = 100, offset: int = 0) -> List[Skill]:
        """
        List all skills with pagination.

        Args:
            limit: Maximum number of skills to return
            offset: Number of skills to skip

        Returns:
            List of Skill instances
        """
        log.debug(f"Listing skills limit={limit}, offset={offset}")
        stmt = (
            select(Skill)
            .order_by(Skill.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, skill_id: str, skill_data: dict) -> Optional[Skill]:
        """
        Update a skill record.

        Args:
            skill_id: UUID string of the skill
            skill_data: Dictionary of fields to update

        Returns:
            Updated Skill if found, None otherwise
        """
        log.info(f"Updating skill id={skill_id}")

        skill = await self.get_by_id(skill_id)
        if not skill:
            log.warning(f"Skill not found for update: id={skill_id}")
            return None

        allowed_fields = {
            "name", "description", "code", "test_cases",
            "skill_metadata", "is_active", "parent_id",
            "skill_type", "applicability", "instructions",
            "termination", "interface",
        }

        for key, value in skill_data.items():
            if key in allowed_fields and hasattr(skill, key):
                setattr(skill, key, value)

        await self.session.flush()
        await self.session.refresh(skill)

        log.info(f"Updated skill id={skill_id}")
        return skill

    async def set_active(self, skill_id: str, is_active: bool) -> Optional[Skill]:
        """
        Set the active status of a skill.

        Args:
            skill_id: UUID string of the skill
            is_active: New active status

        Returns:
            Updated Skill if found, None otherwise
        """
        log.info(f"Setting skill id={skill_id} is_active={is_active}")

        skill = await self.get_by_id(skill_id)
        if not skill:
            log.warning(f"Skill not found: id={skill_id}")
            return None

        skill.is_active = is_active
        await self.session.flush()
        await self.session.refresh(skill)

        return skill

    async def delete(self, skill_id: str) -> bool:
        """
        Delete a skill record.

        Args:
            skill_id: UUID string of the skill

        Returns:
            True if deleted, False if not found
        """
        log.info(f"Deleting skill id={skill_id}")

        skill = await self.get_by_id(skill_id)
        if not skill:
            log.warning(f"Skill not found for delete: id={skill_id}")
            return False

        await self.session.delete(skill)
        await self.session.flush()

        log.info(f"Deleted skill id={skill_id}")
        return True

    async def get_children(self, skill_id: str) -> List[Skill]:
        """
        Get all child skills of a parent skill.

        Used for version tracking - count of children = version index.

        Args:
            skill_id: UUID string of the parent skill

        Returns:
            List of child Skill instances
        """
        log.debug(f"Getting children of skill id={skill_id[:8]}...")
        stmt = (
            select(Skill)
            .where(Skill.parent_id == skill_id)
            .order_by(Skill.created_at.asc())
        )
        result = await self.session.execute(stmt)
        children = list(result.scalars().all())
        log.debug(f"Found {len(children)} children")
        return children

    async def find_by_fingerprint(self, fingerprint: str) -> Optional[Skill]:
        """
        Find a skill by its code fingerprint.

        Used for deduplication to prevent creating duplicate skills.

        Args:
            fingerprint: SHA-256 hash of normalized code

        Returns:
            Skill if found, None otherwise
        """
        log.debug(f"Finding skill by fingerprint={fingerprint[:16]}...")
        stmt = select(Skill).where(
            Skill.skill_metadata["code_fingerprint"].astext == fingerprint
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
