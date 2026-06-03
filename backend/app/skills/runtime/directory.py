import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from app.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class SkillDirectory:
    """Represents a skill stored as a directory."""

    name: str
    version: str
    description: str
    skill_md: str
    metadata: dict
    scripts: dict[str, str]
    requirements: list[str]
    system_packages: list[str] = field(default_factory=list)
    test_cases: list[dict] = field(default_factory=list)

    @property
    def skill_id(self) -> str:
        """Generate unique ID from name."""
        return hashlib.sha256(self.name.encode()).hexdigest()[:12]

    def get_main_code(self) -> str:
        """Get the main script code."""
        return self.scripts.get("main.py", "")

    def get_requirements_txt(self) -> str:
        """Get requirements.txt content."""
        return "\n".join(self.requirements)


class SkillDirectoryService:
    """
    Service for managing skills as directories (OpenClaw-style).

    Directory structure:
    skills/
    └── my_skill/
        ├── SKILL.md           # Metadata + documentation
        ├── scripts/
        │   ├── __init__.py
        │   └── main.py        # Main executable code
        ├── requirements.txt   # pip dependencies
        └── tests/
            └── test_main.py   # Test cases
    """

    SKILL_MD_TEMPLATE = '''---
name: {name}
version: {version}
description: {description}
metadata:
  lumari:
    requires:
      pip: {pip_requirements}
      apt: {apt_requirements}
    entry_point: scripts/main.py
    function: execute
    created_by: {created_by}
    created_at: {created_at}
    skill_id: {skill_id}
---

# {title}

{description}

## Usage

```python
from skills.{name}.scripts.main import execute

result = execute(input_data)
```

## Input

See function signature for required input fields.

## Output

Returns a dict with:
- `success`: bool - Whether the operation succeeded
- `result`: The operation result (on success)
- `error`: Error message (on failure)
'''

    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize the skill directory service.

        Args:
            base_path: Base path for skill directories.
                       Defaults to settings.skill_directory_path
        """
        self.base_path = Path(base_path or settings.skill_directory_path)
        self._ensure_base_path()

    def _ensure_base_path(self) -> None:
        """Ensure base path exists."""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            log.info(f"Skill directory base path: {self.base_path}")
        except Exception as e:
            log.warning(f"Could not create skill directory path: {e}")

    def create_skill_directory(
        self,
        name: str,
        description: str,
        code: str,
        pip_requirements: list[str],
        apt_requirements: Optional[list[str]] = None,
        test_cases: Optional[list[dict]] = None,
        skill_id: Optional[str] = None,
        created_by: str = "skill_team_orchestrator",
    ) -> SkillDirectory:
        """
        Create a new skill directory.

        Args:
            name: Skill name (will be slugified)
            description: Skill description
            code: Main Python code
            pip_requirements: List of pip packages
            apt_requirements: List of apt packages
            test_cases: Optional test cases
            skill_id: Optional skill ID (generated if not provided)
            created_by: Creator identifier

        Returns:
            SkillDirectory object representing the created skill
        """
        name = self._slugify(name)
        apt_requirements = apt_requirements or []
        test_cases = test_cases or []

        skill_path = self.base_path / name

        if skill_path.exists():
            shutil.rmtree(skill_path)
            log.info(f"Removed existing skill directory: {name}")

        skill_path.mkdir(parents=True, exist_ok=True)

        scripts_path = skill_path / "scripts"
        scripts_path.mkdir(exist_ok=True)
        (scripts_path / "__init__.py").write_text("")
        (scripts_path / "main.py").write_text(code)

        (skill_path / "requirements.txt").write_text("\n".join(pip_requirements))

        generated_skill_id = skill_id or hashlib.sha256(name.encode()).hexdigest()[:12]
        skill_md = self._generate_skill_md(
            name=name,
            description=description,
            pip_requirements=pip_requirements,
            apt_requirements=apt_requirements,
            skill_id=generated_skill_id,
            created_by=created_by,
        )
        (skill_path / "SKILL.md").write_text(skill_md)

        if test_cases:
            tests_path = skill_path / "tests"
            tests_path.mkdir(exist_ok=True)
            (tests_path / "__init__.py").write_text("")
            test_code = self._generate_test_file(name, test_cases)
            (tests_path / "test_main.py").write_text(test_code)

        log.info(f"Created skill directory: {skill_path}")

        return self.load_skill(name)

    def load_skill(self, name: str) -> Optional[SkillDirectory]:
        """
        Load a skill directory.

        Args:
            name: Skill name

        Returns:
            SkillDirectory or None if not found
        """
        name = self._slugify(name)
        skill_path = self.base_path / name

        if not skill_path.exists():
            return None

        skill_md_path = skill_path / "SKILL.md"
        if not skill_md_path.exists():
            log.warning(f"Skill {name} missing SKILL.md")
            return None

        skill_md = skill_md_path.read_text()
        metadata = self._parse_frontmatter(skill_md)

        scripts = {}
        scripts_path = skill_path / "scripts"
        if scripts_path.exists():
            for py_file in scripts_path.glob("*.py"):
                if py_file.name != "__init__.py":
                    scripts[py_file.name] = py_file.read_text()

        requirements = []
        req_path = skill_path / "requirements.txt"
        if req_path.exists():
            requirements = [
                line.strip()
                for line in req_path.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            ]

        test_cases = []
        tests_path = skill_path / "tests" / "test_main.py"
        if tests_path.exists():
            test_cases = [{"file": "test_main.py"}]

        return SkillDirectory(
            name=name,
            version=metadata.get("version", "1.0.0"),
            description=metadata.get("description", ""),
            skill_md=skill_md,
            metadata=metadata,
            scripts=scripts,
            requirements=requirements,
            system_packages=metadata.get("metadata", {})
            .get("lumari", {})
            .get("requires", {})
            .get("apt", []),
            test_cases=test_cases,
        )

    def update_skill(
        self,
        name: str,
        code: Optional[str] = None,
        pip_requirements: Optional[list[str]] = None,
        description: Optional[str] = None,
    ) -> Optional[SkillDirectory]:
        """
        Update an existing skill.

        Args:
            name: Skill name
            code: New code (optional)
            pip_requirements: New requirements (optional)
            description: New description (optional)

        Returns:
            Updated SkillDirectory or None if not found
        """
        name = self._slugify(name)
        skill_path = self.base_path / name

        if not skill_path.exists():
            return None

        if code is not None:
            (skill_path / "scripts" / "main.py").write_text(code)

        if pip_requirements is not None:
            (skill_path / "requirements.txt").write_text("\n".join(pip_requirements))

        if description is not None:
            skill = self.load_skill(name)
            if skill:
                skill_md = self._generate_skill_md(
                    name=name,
                    description=description,
                    pip_requirements=pip_requirements or skill.requirements,
                    apt_requirements=skill.system_packages,
                    skill_id=skill.skill_id,
                    created_by=skill.metadata.get("metadata", {})
                    .get("lumari", {})
                    .get("created_by", "unknown"),
                )
                (skill_path / "SKILL.md").write_text(skill_md)

        log.info(f"Updated skill: {name}")
        return self.load_skill(name)

    def delete_skill(self, name: str) -> bool:
        """
        Delete a skill directory.

        Args:
            name: Skill name

        Returns:
            True if deleted, False if not found
        """
        name = self._slugify(name)
        skill_path = self.base_path / name

        if not skill_path.exists():
            return False

        shutil.rmtree(skill_path)
        log.info(f"Deleted skill: {name}")
        return True

    def list_skills(self) -> list[str]:
        """List all skill names."""
        if not self.base_path.exists():
            return []

        return [
            p.name
            for p in self.base_path.iterdir()
            if p.is_dir() and (p / "SKILL.md").exists()
        ]

    def export_skill(self, name: str, export_path: str) -> Optional[str]:
        """
        Export a skill to a specific path.

        Args:
            name: Skill name
            export_path: Destination path

        Returns:
            Path to exported skill or None if not found
        """
        name = self._slugify(name)
        skill_path = self.base_path / name

        if not skill_path.exists():
            return None

        export_dest = Path(export_path) / name
        shutil.copytree(skill_path, export_dest, dirs_exist_ok=True)
        log.info(f"Exported skill {name} to {export_dest}")
        return str(export_dest)

    def import_skill(self, import_path: str) -> Optional[SkillDirectory]:
        """
        Import a skill from external path.

        Args:
            import_path: Source path

        Returns:
            Imported SkillDirectory or None on failure
        """
        src_path = Path(import_path)

        if not src_path.exists():
            return None

        if not (src_path / "SKILL.md").exists():
            log.warning(f"Invalid skill directory (missing SKILL.md): {import_path}")
            return None

        dest_path = self.base_path / src_path.name
        shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
        log.info(f"Imported skill from {import_path}")
        return self.load_skill(src_path.name)

    def _generate_skill_md(
        self,
        name: str,
        description: str,
        pip_requirements: list[str],
        apt_requirements: list[str],
        skill_id: str,
        created_by: str,
    ) -> str:
        """Generate SKILL.md content."""
        return self.SKILL_MD_TEMPLATE.format(
            name=name,
            version="1.0.0",
            title=name.replace("_", " ").title(),
            description=description,
            pip_requirements=pip_requirements,
            apt_requirements=apt_requirements,
            skill_id=skill_id,
            created_by=created_by,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _parse_frontmatter(self, content: str) -> dict:
        """Parse YAML frontmatter from SKILL.md."""
        if not content.startswith("---"):
            return {}

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}

        try:
            return yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError as e:
            log.warning(f"Failed to parse SKILL.md frontmatter: {e}")
            return {}

    def _generate_test_file(self, name: str, test_cases: list[dict]) -> str:
        """Generate pytest test file."""
        tests = [
            f'''"""Tests for {name} skill."""

import pytest
from scripts.main import execute

'''
        ]

        for i, tc in enumerate(test_cases, 1):
            test_name = tc.get("name", f"case_{i}")
            test_input = tc.get("input", tc.get("input_data", {}))
            expected_type = tc.get("expected_output_type", "dict")
            expected_keys = tc.get("expected_keys", ["success"])

            tests.append(
                f'''
def test_{test_name}():
    """Test: {tc.get('description', test_name)}"""
    result = execute({repr(test_input)})

    assert isinstance(result, {expected_type})
    for key in {repr(expected_keys)}:
        assert key in result, f"Missing key: {{key}}"
'''
            )

        return "".join(tests)

    def _slugify(self, name: str) -> str:
        """Convert name to valid directory name."""
        return (
            name.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace(".", "_")
        )
