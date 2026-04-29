"""
Tests for AutonomousSkillBuilder.

Run with: pytest tests/test_autonomous_skill_builder.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.autonomous_skill_builder import (
    AutonomousSkillBuilder,
    SkillDraft,
    ResearchResult,
    CAPABILITY_PACKAGE_HINTS,
)


class TestCapabilityPackageHints:
    """Test the package hints lookup."""

    def test_audio_transcription_hints(self):
        hints = CAPABILITY_PACKAGE_HINTS.get("audio transcription")
        assert hints is not None
        assert "faster-whisper" in hints["pip"]
        assert "ffmpeg" in hints["apt"]

    def test_pdf_reading_hints(self):
        hints = CAPABILITY_PACKAGE_HINTS.get("pdf reading")
        assert hints is not None
        assert "pypdf" in hints["pip"]

    def test_image_ocr_hints(self):
        hints = CAPABILITY_PACKAGE_HINTS.get("image ocr")
        assert hints is not None
        assert "pytesseract" in hints["pip"]
        assert "tesseract-ocr" in hints["apt"]


class TestCodeExtraction:
    """Test code extraction utilities."""

    @pytest.fixture
    def builder(self):
        # Create builder with mocked dependencies
        mock_db = MagicMock()
        return AutonomousSkillBuilder(session_factory=mock_db)

    def test_extract_code_from_markdown(self, builder):
        response = '''Here's the code:

```python
def execute(input_data):
    return {"success": True}
```

This function does X.'''

        code = builder._extract_code(response)
        assert "def execute(input_data):" in code
        assert "return {\"success\": True}" in code

    def test_extract_code_plain(self, builder):
        response = '''import json

def execute(input_data):
    return {"success": True}'''

        code = builder._extract_code(response)
        assert "import json" in code
        assert "def execute(input_data):" in code

    def test_extract_imports(self, builder):
        code = '''import json
import os
from pathlib import Path
from faster_whisper import WhisperModel

def execute(data):
    pass'''

        imports = builder._extract_imports(code)
        assert "json" in imports
        assert "os" in imports
        assert "pathlib" in imports
        assert "faster_whisper" in imports

    def test_imports_to_packages(self, builder):
        imports = ["json", "os", "faster_whisper", "pydub"]
        recommended = ["faster-whisper"]

        packages = builder._imports_to_packages(imports, recommended)

        # Standard lib should be excluded
        assert "json" not in packages
        assert "os" not in packages

        # Package mappings should work
        assert "faster-whisper" in packages
        assert "pydub" in packages


class TestSkillDraftGeneration:
    """Test skill draft building."""

    @pytest.fixture
    def builder(self):
        mock_db = MagicMock()
        return AutonomousSkillBuilder(session_factory=mock_db)

    def test_build_test_code(self, builder):
        draft = SkillDraft(
            name="test_skill",
            description="Test",
            code="def execute(input_data): return {'success': True}",
        )

        test_code = builder._build_test_code(
            draft,
            test_input={"file_path": "/test.txt"},
            expected_output_type="dict",
        )

        assert "execute(test_input)" in test_code
        assert "TEST PASSED" in test_code
        assert '"/test.txt"' in test_code

    def test_module_to_package_mapping(self, builder):
        assert builder._module_to_package("cv2") == "opencv-python"
        assert builder._module_to_package("PIL") == "Pillow"
        assert builder._module_to_package("faster_whisper") == "faster-whisper"
        assert builder._module_to_package("unknown_module") == "unknown_module"


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests (require Docker)."""

    @pytest.fixture
    def builder(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        return AutonomousSkillBuilder(session_factory=mock_db)

    async def test_research_with_known_capability(self, builder):
        """Test that research returns known package hints."""
        result = await builder._research_capability("audio transcription")

        assert "faster-whisper" in result.recommended_packages or \
               "openai-whisper" in result.recommended_packages
        assert "ffmpeg" in result.recommended_system_packages

    async def test_research_with_hints(self, builder):
        """Test that user hints are included in research."""
        result = await builder._research_capability(
            "custom capability",
            hints={"pip": ["custom-package"], "apt": ["custom-apt"]}
        )

        assert "custom-package" in result.recommended_packages
        assert "custom-apt" in result.recommended_system_packages

    @pytest.mark.skip(reason="Requires LLM API - run manually")
    async def test_generate_skill_code(self, builder):
        """Test skill code generation."""
        research = ResearchResult(
            query="pdf reading",
            recommended_packages=["pypdf"],
            summary="Use pypdf to read PDF files.",
        )

        draft = await builder._generate_skill_code("pdf reading", research)

        assert draft.name == "skill_pdf_reading"
        assert "def execute" in draft.code
        assert "pypdf" in draft.pip_requirements

    @pytest.mark.skip(reason="Requires Docker + LLM - run manually")
    async def test_build_simple_skill(self, builder):
        """Test building a simple skill end-to-end."""
        result = await builder.build_skill(
            capability="json processing",
            test_input={"data": {"key": "value"}},
        )

        # This may or may not succeed depending on LLM output
        print(f"Build result: success={result.success}, iterations={result.iterations}")
        if not result.success:
            print(f"Error: {result.final_error}")
