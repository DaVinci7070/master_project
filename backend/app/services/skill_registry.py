"""
Skill Registry - In-memory skill registry with hot-reload support.

Provides instant skill availability without server restart:
- Skills are compiled and loaded into memory
- Updates are reflected immediately
- Tracks execution statistics per skill
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import CodeType
from typing import TYPE_CHECKING, Any, Callable, Optional

from app.core.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


@dataclass
class LoadedSkill:
    """A skill loaded into memory for fast execution."""

    id: str
    name: str
    code: str  # Source code
    compiled: CodeType  # Compiled code object
    metadata: dict
    loaded_at: datetime
    execution_count: int = 0
    last_executed: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0
    avg_execution_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def get_execute_function(self) -> Optional[Callable]:
        """
        Get the execute function from the compiled code.

        Returns:
            The execute function or None if not found
        """
        try:
            namespace: dict[str, Any] = {}
            exec(self.compiled, namespace)
            return namespace.get("execute")
        except Exception as e:
            log.error(f"Failed to get execute function for {self.name}: {e}")
            return None


class SkillRegistry:
    """
    Singleton registry for hot-loaded skills.

    Skills are loaded into memory for fast access.
    Updates are reflected immediately without restart.

    Usage:
        registry = SkillRegistry.get_instance()
        await registry.load_skill(skill)
        loaded = registry.get_skill(skill_id)
    """

    _instance: Optional["SkillRegistry"] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self):
        """Initialize the registry (use get_instance() instead)."""
        self._skills: dict[str, LoadedSkill] = {}
        self._name_index: dict[str, str] = {}  # name -> id
        self._capability_index: dict[str, list[str]] = {}  # capability -> [skill_ids]
        self._initialized: bool = False

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        """Get the singleton registry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    async def load_skill(self, skill: Any) -> LoadedSkill:
        """
        Load a skill into memory.

        Args:
            skill: Skill model object with id, name, code, skill_metadata

        Returns:
            LoadedSkill object

        Raises:
            SyntaxError: If code cannot be compiled
        """
        async with self._lock:
            try:
                compiled = compile(skill.code, f"<skill:{skill.id}>", "exec")
            except SyntaxError as e:
                log.error(f"Failed to compile skill {skill.name}: {e}")
                raise

            loaded = LoadedSkill(
                id=skill.id,
                name=skill.name,
                code=skill.code,
                compiled=compiled,
                metadata=skill.skill_metadata or {},
                loaded_at=datetime.now(timezone.utc),
            )

            self._skills[skill.id] = loaded
            self._name_index[skill.name] = skill.id

            # Index by capability
            capability = loaded.metadata.get("affected_capability")
            if capability:
                if capability not in self._capability_index:
                    self._capability_index[capability] = []
                if skill.id not in self._capability_index[capability]:
                    self._capability_index[capability].append(skill.id)

            log.info(f"Loaded skill into registry: {skill.name} ({skill.id})")
            return loaded

    async def unload_skill(self, skill_id: str) -> bool:
        """
        Unload a skill from memory.

        Args:
            skill_id: ID of skill to unload

        Returns:
            True if unloaded, False if not found
        """
        async with self._lock:
            if skill_id not in self._skills:
                return False

            skill = self._skills.pop(skill_id)

            # Remove from name index
            if skill.name in self._name_index:
                del self._name_index[skill.name]

            # Remove from capability index
            for capability, skill_ids in self._capability_index.items():
                if skill_id in skill_ids:
                    skill_ids.remove(skill_id)

            log.info(f"Unloaded skill from registry: {skill.name}")
            return True

    async def reload_skill(self, skill: Any) -> LoadedSkill:
        """
        Reload a skill (update in place).

        Args:
            skill: Updated skill model object

        Returns:
            Reloaded LoadedSkill object
        """
        await self.unload_skill(skill.id)
        return await self.load_skill(skill)

    def get_skill(self, skill_id: str) -> Optional[LoadedSkill]:
        """Get a loaded skill by ID."""
        return self._skills.get(skill_id)

    def get_skill_by_name(self, name: str) -> Optional[LoadedSkill]:
        """Get a loaded skill by name."""
        skill_id = self._name_index.get(name)
        if skill_id:
            return self._skills.get(skill_id)
        return None

    def get_skills_for_capability(self, capability: str) -> list[LoadedSkill]:
        """Get all skills that handle a capability."""
        skill_ids = self._capability_index.get(capability, [])
        return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def has_skill(self, skill_id: str) -> bool:
        """Check if a skill is loaded."""
        return skill_id in self._skills

    def has_skill_by_name(self, name: str) -> bool:
        """Check if a skill is loaded by name."""
        return name in self._name_index

    def record_execution(
        self,
        skill_id: str,
        success: bool,
        execution_time_ms: float = 0.0,
    ) -> None:
        """
        Record a skill execution for statistics.

        Args:
            skill_id: ID of executed skill
            success: Whether execution succeeded
            execution_time_ms: Execution time in milliseconds
        """
        skill = self._skills.get(skill_id)
        if skill:
            skill.execution_count += 1
            skill.last_executed = datetime.now(timezone.utc)

            if success:
                skill.success_count += 1
            else:
                skill.failure_count += 1

            # Update rolling average execution time
            if execution_time_ms > 0:
                total_time = skill.avg_execution_ms * (skill.execution_count - 1)
                skill.avg_execution_ms = (total_time + execution_time_ms) / skill.execution_count

    async def execute_skill(
        self,
        skill_id: str,
        input_data: dict,
    ) -> dict:
        """
        Execute a loaded skill.

        Args:
            skill_id: ID of skill to execute
            input_data: Input data for the skill

        Returns:
            Skill execution result

        Raises:
            KeyError: If skill not found
            Exception: If execution fails
        """
        skill = self._skills.get(skill_id)
        if not skill:
            raise KeyError(f"Skill not found: {skill_id}")

        start_time = datetime.now(timezone.utc)
        success = False

        try:
            execute_fn = skill.get_execute_function()
            if not execute_fn:
                raise ValueError(f"Skill {skill.name} has no execute function")

            result = execute_fn(input_data)
            success = result.get("success", False) if isinstance(result, dict) else False
            return result

        except Exception as e:
            log.error(f"Skill execution failed: {skill.name}: {e}")
            return {"success": False, "error": str(e)}

        finally:
            execution_time_ms = (
                datetime.now(timezone.utc) - start_time
            ).total_seconds() * 1000
            self.record_execution(skill_id, success, execution_time_ms)

    async def initialize(self, db: "AsyncSession") -> int:
        """
        Load all active skills from database on startup.

        Args:
            db: Database session

        Returns:
            Number of skills loaded
        """
        from sqlalchemy import select
        from app.models.sql.versioned_models import Skill

        if self._initialized:
            log.warning("Registry already initialized")
            return len(self._skills)

        try:
            result = await db.execute(
                select(Skill).where(Skill.is_active == True)
            )
            skills = result.scalars().all()

            count = 0
            for skill in skills:
                try:
                    await self.load_skill(skill)
                    count += 1
                except Exception as e:
                    log.warning(f"Failed to load skill {skill.id}: {e}")

            self._initialized = True
            log.info(f"Skill registry initialized with {count} skills")
            return count

        except Exception as e:
            log.error(f"Failed to initialize skill registry: {e}")
            return 0

    def get_all_skills(self) -> list[LoadedSkill]:
        """Get all loaded skills."""
        return list(self._skills.values())

    def stats(self) -> dict:
        """Get registry statistics."""
        skills_stats = []
        for skill in self._skills.values():
            skills_stats.append({
                "id": skill.id,
                "name": skill.name,
                "executions": skill.execution_count,
                "success_rate": round(skill.success_rate, 2),
                "avg_execution_ms": round(skill.avg_execution_ms, 2),
                "last_executed": skill.last_executed.isoformat() if skill.last_executed else None,
            })

        return {
            "initialized": self._initialized,
            "total_skills": len(self._skills),
            "capabilities_indexed": len(self._capability_index),
            "total_executions": sum(s.execution_count for s in self._skills.values()),
            "skills": skills_stats,
        }

    def clear(self) -> None:
        """Clear all loaded skills (for testing)."""
        self._skills.clear()
        self._name_index.clear()
        self._capability_index.clear()
        self._initialized = False
        log.info("Skill registry cleared")


# Convenience functions for global access
def get_registry() -> SkillRegistry:
    """Get the global skill registry instance."""
    return SkillRegistry.get_instance()


async def load_skill_to_registry(skill: Any) -> LoadedSkill:
    """Load a skill into the global registry."""
    return await get_registry().load_skill(skill)


async def unload_skill_from_registry(skill_id: str) -> bool:
    """Unload a skill from the global registry."""
    return await get_registry().unload_skill(skill_id)
