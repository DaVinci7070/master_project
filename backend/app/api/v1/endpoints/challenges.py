"""
API endpoints for challenge submission and execution.

Provides endpoints for submitting challenges, triggering capability assessment,
and starting execution.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies.dependencies import get_db_session
from app.models.sql.intervention_models import BlockedChallenge, UserSettings
from app.models.schemas.analysis_schemas import (
    CapabilityAssessment,
    CapabilityGap,
    ConfidenceLevel,
    GapType,
    GapSeverity,
    ChallengeAnalysisRequest,
)
from app.orchestration.analysis.orchestrator import create_pre_execution_orchestrator
from app.core.llm_client import create_llm_fn, create_embedding_fn, create_structured_llm_fn
from app.models.schemas.intervention_schemas import (
    BuildPlan,
    BuildPlanItem,
    BuildPlanStatus,
    BuildPlanResponse,
    BuildPlanApprovalRequest,
    UserSettings as UserSettingsSchema,
)
from app.services.build_plan_service import BuildPlanService
from app.services.gap_verification_service import GapVerificationService
from app.services.autonomous_skill_builder import AutonomousSkillBuilder
from app.services.autonomous_executor_service import AutonomousExecutorService, get_executor

router = APIRouter(prefix="/challenges", tags=["challenges"])


# ============================================================================
# Dependency Detection Helpers
# ============================================================================
# These functions ensure skills have their dependencies installed even if
# the skill metadata is missing pip_requirements (e.g., old skills)

# Capability-based default requirements
CAPABILITY_DEFAULT_REQUIREMENTS = {
    "audio transcription": {
        "pip": ["faster-whisper", "pydub"],
        "apt": ["ffmpeg"],
    },
    "pdf reading": {
        "pip": ["pypdf", "pdfplumber"],
        "apt": [],
    },
    "pdf file reading": {
        "pip": ["pypdf", "pdfplumber"],
        "apt": [],
    },
    "image ocr": {
        "pip": ["pytesseract", "Pillow"],
        "apt": ["tesseract-ocr"],
    },
    "image ocr text extraction": {
        "pip": ["pytesseract", "Pillow"],
        "apt": ["tesseract-ocr"],
    },
    "excel reading": {
        "pip": ["openpyxl", "pandas"],
        "apt": [],
    },
    "excel spreadsheet reading": {
        "pip": ["openpyxl", "pandas"],
        "apt": [],
    },
    "word document reading": {
        "pip": ["python-docx"],
        "apt": [],
    },
    "video transcription": {
        "pip": ["faster-whisper", "moviepy", "pydub"],
        "apt": ["ffmpeg"],
    },
}

# Import name to pip package mapping
IMPORT_TO_PIP = {
    'cv2': 'opencv-python',
    'PIL': 'Pillow',
    'sklearn': 'scikit-learn',
    'yaml': 'pyyaml',
    'bs4': 'beautifulsoup4',
    'docx': 'python-docx',
    'faster_whisper': 'faster-whisper',
    'whisper': 'openai-whisper',
    'pydub': 'pydub',
    'pytesseract': 'pytesseract',
    'easyocr': 'easyocr',
    'pypdf': 'pypdf',
    'pdfplumber': 'pdfplumber',
    'fitz': 'PyMuPDF',
    'openpyxl': 'openpyxl',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'requests': 'requests',
    'httpx': 'httpx',
    'aiohttp': 'aiohttp',
}

# Standard library modules (don't need pip install)
STDLIB_MODULES = {
    'os', 'sys', 'json', 're', 'time', 'datetime', 'pathlib', 'io',
    'subprocess', 'tempfile', 'shutil', 'glob', 'copy', 'math',
    'random', 'collections', 'itertools', 'functools', 'typing',
    'base64', 'hashlib', 'uuid', 'logging', 'warnings', 'traceback',
    'asyncio', 'concurrent', 'threading', 'multiprocessing',
}


def _detect_pip_requirements(code: str, capability: str) -> list[str]:
    """
    Detect pip requirements from skill code and capability type.

    This ensures dependencies are installed even if metadata is missing.
    CRITICAL: Always includes capability-specific requirements first,
    then adds any additional imports detected in the code.
    """
    import re
    requirements = []

    # 1. Get defaults for this capability type - ALWAYS include these
    capability_lower = capability.lower()
    if capability_lower in CAPABILITY_DEFAULT_REQUIREMENTS:
        requirements.extend(CAPABILITY_DEFAULT_REQUIREMENTS[capability_lower]["pip"])
        log.info(f"Added default pip requirements for '{capability}': {requirements}")

    # 2. Detect imports from code
    import_pattern = re.compile(r'^(?:from|import)\s+(\w+)', re.MULTILINE)
    imports = import_pattern.findall(code)

    for imp in imports:
        if imp in STDLIB_MODULES:
            continue

        # Map import name to pip package
        if imp in IMPORT_TO_PIP:
            pkg = IMPORT_TO_PIP[imp]
            if pkg not in requirements:
                requirements.append(pkg)
        elif imp not in requirements:
            # Assume import name is package name
            requirements.append(imp)

    return list(dict.fromkeys(requirements))  # Remove duplicates


def _detect_system_packages(capability: str) -> list[str]:
    """
    Detect system (apt) packages needed for a capability.
    """
    capability_lower = capability.lower()
    if capability_lower in CAPABILITY_DEFAULT_REQUIREMENTS:
        return CAPABILITY_DEFAULT_REQUIREMENTS[capability_lower]["apt"]
    return []
log = logging.getLogger(__name__)


# Request models
class AnalyzeChallengeRequest(BaseModel):
    """Request body for direct challenge analysis."""
    challenge_text: str
    execution_id: str
    project_id: str = "default"
    include_cross_project: bool = True


# Response models
class ChallengeCreateResponse(BaseModel):
    """Response after creating a challenge."""
    id: str
    execution_id: str
    challenge_text: str
    status: str
    created_at: str


class ChallengeAssessmentResponse(BaseModel):
    """Capability assessment result for a challenge."""
    challenge_id: str
    execution_id: str
    confidence: str  # CAN_DO, MAYBE, CANNOT_DO
    reasoning: str
    top_factors: list[str]
    gaps: list[dict]  # CapabilityGap as dict
    improvement_suggestions: list[str]
    route_decision: str  # execute or developer_team
    assessed_at: str


class ChallengeExecutionResponse(BaseModel):
    """Response after starting challenge execution."""
    challenge_id: str
    execution_id: str
    status: str
    message: str
    started_at: str


class ChallengeStatusResponse(BaseModel):
    """Current status of a challenge."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    execution_id: str
    challenge_text: str
    status: str
    attempt_number: int
    max_attempts: int
    assessment_result: Optional[dict] = None
    gaps_snapshot: list[dict] = Field(default_factory=list)
    built_capability_ids: list[str] = Field(default_factory=list)
    execution_results: Optional[dict] = None  # Orchestrator output after execution
    created_at: str
    updated_at: Optional[str] = None
    resolved_at: Optional[str] = None


class ChallengeAnalysisFullResponse(BaseModel):
    """Full analysis response matching frontend ChallengeAnalysisResponse type."""
    challenge_id: str  # ID for executing this challenge
    assessment: dict  # CapabilityAssessment as dict
    challenge_text: str
    execution_id: str
    analyzed_at: str
    route_decision: str  # 'execute' or 'developer_team'


class ChallengeResultsResponse(BaseModel):
    """Response containing execution results from orchestrator."""
    challenge_id: str
    execution_id: str
    status: str
    execution_results: Optional[dict] = None
    duration_ms: Optional[int] = None
    agents_executed: int = 0
    completed_at: Optional[str] = None


class ChallengeAnalysisWithPlanResponse(BaseModel):
    """Full analysis response including build plan when capabilities are missing."""
    challenge_id: str
    assessment: dict
    challenge_text: str
    execution_id: str
    analyzed_at: str
    route_decision: str  # 'execute' or 'developer_team'
    # Build plan fields (only populated when route_decision == 'developer_team')
    build_plan: Optional[dict] = None
    build_plan_status: Optional[str] = None
    auto_apply_enabled: bool = False
    message: str = ""


class UserSettingsResponse(BaseModel):
    """User settings response."""
    auto_apply: bool
    notify_on_build: bool
    notify_on_execution: bool


class UserSettingsUpdateRequest(BaseModel):
    """Request to update user settings."""
    auto_apply: Optional[bool] = None
    notify_on_build: Optional[bool] = None
    notify_on_execution: Optional[bool] = None


@router.post("/analyze", response_model=ChallengeAnalysisWithPlanResponse)
async def analyze_challenge_direct(
    request: AnalyzeChallengeRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeAnalysisWithPlanResponse:

    log.info(f"Direct challenge analysis: execution_id={request.execution_id}")

    # Generate challenge ID
    challenge_id = str(uuid.uuid4())

    # Create challenge record
    challenge = BlockedChallenge(
        id=challenge_id,
        execution_id=request.execution_id,
        project_id=request.project_id,
        challenge_text=request.challenge_text,
        assessment_result={},
        gaps_snapshot=[],
        status="analyzing",
    )

    session.add(challenge)
    await session.commit()

    # Perform capability assessment using PreExecutionOrchestrator
    try:
        embedding_fn = create_embedding_fn()
        structured_llm_fn = create_structured_llm_fn()
        orchestrator = await create_pre_execution_orchestrator(
            db=session,
            embedding_fn=embedding_fn,
            structured_llm_fn=structured_llm_fn,
        )

        # Build analysis request
        analysis_request = ChallengeAnalysisRequest(
            challenge_text=request.challenge_text,
            execution_id=request.execution_id,
            project_id=request.project_id,
            include_cross_project=request.include_cross_project
        )

        # Run the orchestrator analysis
        analysis_response = await orchestrator.analyze_challenge(analysis_request)

        # Extract assessment and route decision from response
        assessment = analysis_response.assessment
        route_decision = analysis_response.route_decision

        log.info(f"Orchestrator analysis complete: confidence={assessment.confidence.value}, route={route_decision}")

    except Exception as e:
        log.error(f"Orchestrator analysis failed, using fallback: {e}")
        # Fallback to simple assessment if orchestrator fails
        assessment = CapabilityAssessment(
            confidence=ConfidenceLevel.CAN_DO,
            reasoning=f"Fallback assessment (orchestrator error: {str(e)[:100]})",
            top_factors=["Fallback mode active"],
            gaps=[],
            improvement_suggestions=[],
            similar_past_success=False,
        )
        route_decision = "execute"

    # Update challenge with assessment
    challenge.assessment_result = assessment.model_dump()
    challenge.gaps_snapshot = [g.model_dump() for g in assessment.gaps]
    challenge.status = "assessed"
    await session.commit()

    # Route decision already determined by orchestrator (or fallback)
    # Generate build plan if routing to developer team
    build_plan_dict = None
    auto_apply_enabled = False
    message = ""

    if route_decision == "developer_team" and assessment.gaps:
        # PRE-CHECK: Filter out gaps that are already satisfied by existing capabilities
        # This prevents rebuilding skills that already exist
        verification_service = GapVerificationService(session)
        remaining_gaps = []

        for gap in assessment.gaps:
            gap_dict = gap.model_dump()
            verification_result = await verification_service.verify_gap_closure(gap_dict)

            if verification_result.is_closed:
                log.info(
                    f"Gap already satisfied: '{gap.affected_capability}' "
                    f"by {verification_result.closed_by_artifact_type}/{verification_result.closed_by_artifact_id[:8] if verification_result.closed_by_artifact_id else 'N/A'}..."
                )
            else:
                remaining_gaps.append(gap)

        # Update route decision if all gaps are already satisfied
        if not remaining_gaps:
            log.info(f"All {len(assessment.gaps)} gaps already satisfied by existing capabilities - routing to execute")
            route_decision = "execute"
            message = f"Alle {len(assessment.gaps)} benötigten Capabilities existieren bereits. Bereit zur Ausführung."
        else:
            log.info(f"{len(assessment.gaps) - len(remaining_gaps)} gaps already satisfied, {len(remaining_gaps)} remaining")
            # Update assessment gaps to only include remaining gaps
            assessment.gaps = remaining_gaps

    if route_decision == "developer_team" and assessment.gaps:
        build_plan_service = BuildPlanService(session)
        build_plan = build_plan_service.generate_plan_from_gaps(
            challenge_id=challenge_id,
            gaps=[g.model_dump() for g in assessment.gaps]
        )
        build_plan_dict = build_plan.model_dump(mode="json")

        # Save plan to challenge
        challenge.build_plan = build_plan_dict
        challenge.build_plan_status = BuildPlanStatus.PENDING.value

        # Check auto-apply setting
        auto_apply_enabled = await build_plan_service.is_auto_apply_enabled()

        if auto_apply_enabled:
            message = "Build-Plan wird automatisch ausgeführt (Auto-Apply aktiv)"
            challenge.build_plan_status = BuildPlanStatus.APPROVED.value
            # Trigger capability building in background
            background_tasks.add_task(
                _run_capability_building,
                challenge_id=challenge_id,
            )
        else:
            message = "Build-Plan erstellt. Bitte genehmigen oder ablehnen."

        await session.commit()

    return ChallengeAnalysisWithPlanResponse(
        challenge_id=challenge_id,
        assessment=assessment.model_dump(),
        challenge_text=request.challenge_text,
        execution_id=request.execution_id,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        route_decision=route_decision,
        build_plan=build_plan_dict,
        build_plan_status=challenge.build_plan_status if build_plan_dict else None,
        auto_apply_enabled=auto_apply_enabled,
        message=message,
    )


# File upload endpoint - system autonomously handles any file format
@router.post("/upload", response_model=ChallengeAnalysisWithPlanResponse)
async def upload_challenge_file(
    file: UploadFile = File(..., description="Challenge file (any format)"),
    project_id: str = Form("default", description="Project ID"),
    execution_id: str = Form(None, description="Execution ID (auto-generated if not provided)"),
    instructions: str = Form("", description="Additional instructions for processing the file"),
    background_tasks: BackgroundTasks = None,
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeAnalysisWithPlanResponse:
    """
    Upload a challenge file in ANY format.

    The system autonomously:
    1. Detects the file type
    2. Assesses if it has the capability to read this format
    3. If not, creates a skill to handle this file type
    4. Processes the file and analyzes the challenge

    Supported via dynamic skill creation:
    - Text, JSON, XML, YAML, CSV
    - PDF, Word, Excel, PowerPoint
    - Images (OCR), Audio (transcription)
    - Any other format the system learns to handle
    """
    import mimetypes
    import os

    log.info(f"File upload: {file.filename}, size={file.size}, type={file.content_type}")

    # Read file content
    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(content) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 50MB")

    # Detect file type
    file_ext = file.filename.split('.')[-1].lower() if '.' in file.filename else 'unknown'
    content_type = file.content_type or mimetypes.guess_type(file.filename)[0] or 'application/octet-stream'

    # Known binary formats - detect by extension/content-type FIRST
    # These should never be decoded as text
    BINARY_EXTENSIONS = {
        # Documents
        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
        # Images
        'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff', 'ico', 'svg',
        # Audio
        'mp3', 'wav', 'ogg', 'opus', 'm4a', 'flac', 'aac', 'wma',
        # Video
        'mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm',
        # Archives
        'zip', 'tar', 'gz', 'rar', '7z',
        # Other binary
        'exe', 'dll', 'so', 'dylib', 'bin',
    }

    BINARY_MIMETYPES = {
        'application/pdf', 'application/msword',
        'application/vnd.openxmlformats-officedocument',
        'image/', 'audio/', 'video/',
        'application/zip', 'application/x-tar',
        'application/octet-stream',
    }

    # Determine if file is binary
    is_binary = (
        file_ext in BINARY_EXTENSIONS or
        any(content_type.startswith(mime) for mime in BINARY_MIMETYPES)
    )

    # For text files, try UTF-8 decode
    text_content = None
    if not is_binary:
        try:
            text_content = content.decode('utf-8')
            # Double-check: if text contains null bytes, it's binary
            if '\x00' in text_content:
                is_binary = True
                text_content = None
        except UnicodeDecodeError:
            is_binary = True

    # Audio formats that can be transcribed directly via Whisper API
    AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg', 'opus', 'm4a', 'flac', 'webm', 'mp4', 'mpeg', 'mpga'}

    # Build challenge text - handle binary files appropriately
    if is_binary:
        # Save binary file to temp storage
        # Path: endpoints -> v1 -> api -> app/uploads
        upload_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)

        file_id = str(uuid.uuid4())
        stored_filename = f"{file_id}.{file_ext}"
        file_path = os.path.join(upload_dir, stored_filename)

        with open(file_path, 'wb') as f:
            f.write(content)

        log.info(f"Saved binary file to: {file_path}")

        # Check if this is an audio file
        if file_ext in AUDIO_EXTENSIONS:
            # Don't transcribe synchronously — it takes 60-90s in Docker sandbox.
            # Instead, mark as needing transcription and handle in background.
            from app.models.sql.versioned_models import Skill

            # Check if transcription skill exists
            skill_result = await session.execute(
                select(Skill).where(
                    (Skill.name.like("%audio%transcription%")) &
                    (Skill.is_active == True)
                )
            )
            existing_skill = skill_result.scalar_one_or_none()

            if existing_skill:
                # Skill exists — transcription will happen in background during execution
                log.info(f"Audio transcription skill available: {existing_skill.name} — will transcribe in background")
                file_info = f"""[UPLOADED AUDIO FILE - READY FOR TRANSCRIPTION]
Original Filename: {file.filename}
File Extension: .{file_ext}
Size: {len(content)} bytes
Storage Path: {file_path}
Transcription Skill: {existing_skill.name}

[TASK]
Transcribe this audio file and analyze the content.
"""
            else:
                # No skill or skill failed - create capability gap for autonomous building
                log.info(f"No working audio transcription skill - will build one autonomously")
                file_info = f"""[UPLOADED AUDIO FILE - NEEDS SKILL]
Filename: {file.filename}
File Extension: .{file_ext}
Content-Type: {content_type}
Size: {len(content)} bytes
Storage Path: {file_path}

[AUTONOMOUS ACTION REQUIRED]
The system will autonomously:
1. Build an audio transcription skill using faster-whisper (open source)
2. Install required packages: faster-whisper, ffmpeg
3. Test the skill in sandbox
4. Transcribe this audio file
5. Return the result

[CAPABILITY TO BUILD]
Capability: audio transcription
Packages: faster-whisper, pydub
System: ffmpeg
Method: Open Source (NO external API)
"""
        else:
            # Other binary files (PDF, images, etc.) - create capability gap
            processing_type = "Image OCR" if file_ext in {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff'} else \
                              "Document parsing" if file_ext in {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'} else \
                              "Binary file processing"

            file_info = f"""[UPLOADED BINARY FILE - NEEDS SKILL]
Filename: {file.filename}
File Extension: .{file_ext}
Content-Type: {content_type}
Size: {len(content)} bytes
Storage Path: {file_path}

[AUTONOMOUS ACTION REQUIRED]
The system will autonomously:
1. Build a skill to read/parse .{file_ext} files
2. Install required packages via pip/apt
3. Test the skill in sandbox
4. Extract content from the file
5. Analyze the content

[CAPABILITY TO BUILD]
Capability: {file_ext} file reading
Processing type: {processing_type}
Method: Open Source (NO external API)
"""
    else:
        # For text files, include content directly (safe for database)
        file_info = f"""[UPLOADED TEXT FILE]
Filename: {file.filename}
File Extension: .{file_ext}
Content-Type: {content_type}
Size: {len(content)} bytes

[FILE CONTENT]
{text_content[:50000]}{"..." if len(text_content) > 50000 else ""}
"""

    # Append user instructions if provided
    if instructions and instructions.strip():
        file_info += f"\n\n[USER INSTRUCTIONS]\n{instructions.strip()}\n"

    # Generate IDs
    if not execution_id:
        execution_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())

    # Create challenge record
    challenge = BlockedChallenge(
        id=challenge_id,
        execution_id=execution_id,
        project_id=project_id,
        challenge_text=file_info,
        assessment_result={},
        gaps_snapshot=[],
        status="analyzing",
    )

    session.add(challenge)
    await session.commit()

    # Check if system can handle this file type
    verification_service = GapVerificationService(session)
    gaps: list[CapabilityGap] = []

    # Capability needed based on file type
    file_type_capabilities = {
        # Documents
        'pdf': 'pdf file reading',
        'docx': 'word document reading',
        'doc': 'word document reading',
        'xlsx': 'excel spreadsheet reading',
        'xls': 'excel spreadsheet reading',
        'csv': 'csv file parsing',
        'pptx': 'powerpoint reading',
        'ppt': 'powerpoint reading',
        'odt': 'document reading',
        'ods': 'spreadsheet reading',
        # Images (OCR)
        'png': 'image ocr text extraction',
        'jpg': 'image ocr text extraction',
        'jpeg': 'image ocr text extraction',
        'gif': 'image ocr text extraction',
        'bmp': 'image ocr text extraction',
        'webp': 'image ocr text extraction',
        'tiff': 'image ocr text extraction',
        # Audio
        'mp3': 'audio transcription',
        'wav': 'audio transcription',
        'm4a': 'audio transcription',
        'ogg': 'audio transcription',
        'opus': 'audio transcription',
        'flac': 'audio transcription',
        'aac': 'audio transcription',
        # Video
        'mp4': 'video transcription',
        'mov': 'video transcription',
        'avi': 'video transcription',
        'mkv': 'video transcription',
        'webm': 'video transcription',
    }

    required_capability = file_type_capabilities.get(file_ext)

    # Check if audio skill is available (no gap needed)
    audio_transcribed = "[TRANSCRIBED AUDIO FILE]" in file_info or "[READY FOR TRANSCRIPTION]" in file_info

    if required_capability and is_binary and not audio_transcribed:
        # Check if system has this capability
        cap_result = await verification_service.capability_exists(required_capability)
        if not cap_result.exists:
            gaps.append(CapabilityGap(
                id=str(uuid.uuid4()),
                gap_type=GapType.MISSING_SKILL,
                severity=GapSeverity.CRITICAL,
                affected_capability=required_capability,
                description=f"System needs ability to read and extract content from .{file_ext} files",
                suggested_fix=f"Build a skill that can parse {file_ext.upper()} files and extract text content",
                evidence=[f"User uploaded a .{file_ext} file that requires specialized parsing"]
            ))

    # Also check for content-specific capabilities (financial, technical, etc.)
    if text_content:
        text_lower = text_content.lower()
        has_financial = any(term in text_lower for term in [
            'roi', 'tco', 'berechnung', 'calculation', 'rendite', 'kosten',
            'investment', 'payback', 'npv', 'irr', 'cashflow', 'budget'
        ])

        if has_financial:
            fin_cap_result = await verification_service.capability_exists("financial calculation")
            if not fin_cap_result.exists:
                gaps.append(CapabilityGap(
                    id=str(uuid.uuid4()),
                    gap_type=GapType.MISSING_SKILL,
                    severity=GapSeverity.CRITICAL,
                    affected_capability="financial calculation",
                    description="System needs ability to perform ROI, TCO, NPV calculations",
                    suggested_fix="Build financial calculation skill with standard formulas",
                    evidence=["Financial terms found in file content"]
                ))

    # Determine route and confidence
    if gaps:
        route_decision = "developer_team"
        confidence = ConfidenceLevel.CANNOT_DO
    else:
        route_decision = "execute"
        confidence = ConfidenceLevel.CAN_DO

    assessment = CapabilityAssessment(
        confidence=confidence,
        reasoning=f"Analyzed uploaded file: {file.filename} ({file_ext})",
        gaps=gaps,
        top_contributing_factors=[
            f"File type: {file_ext}",
            f"Binary: {is_binary}",
            f"Size: {len(content)} bytes"
        ],
        improvement_suggestions=[
            f"System will autonomously develop skills to handle .{file_ext} files" if gaps else "File can be processed"
        ],
        execution_path=route_decision
    )

    # Update challenge
    challenge.assessment_result = assessment.model_dump()
    challenge.gaps_snapshot = [g.model_dump() for g in gaps]
    challenge.status = "needs_capabilities" if gaps else "ready"
    await session.commit()

    # Build plan if needed
    build_plan_dict = None
    auto_apply_enabled = False
    message = f"File '{file.filename}' uploaded successfully"

    if gaps:
        plan_service = BuildPlanService(session)
        # generate_plan_from_gaps expects list[dict], not list[CapabilityGap]
        plan = plan_service.generate_plan_from_gaps(challenge_id, [g.model_dump() for g in gaps])

        user_settings = await session.execute(
            select(UserSettings).where(UserSettings.user_id == "default")
        )
        settings = user_settings.scalar_one_or_none()
        auto_apply_enabled = settings.auto_apply if settings else False

        build_plan_dict = {
            "challenge_id": plan.challenge_id,
            "items": [item.model_dump() for item in plan.items],
            "total_gaps": plan.total_gaps,
            "critical_gaps": plan.critical_gaps,
            "confidence_after_build": plan.confidence_after_build,
            "created_at": plan.created_at.isoformat() if hasattr(plan.created_at, 'isoformat') else str(plan.created_at),
        }

        challenge.build_plan = build_plan_dict
        challenge.build_plan_status = BuildPlanStatus.PENDING.value
        await session.commit()

        message = f"File uploaded. System needs to develop {len(gaps)} capability(ies) to process this file type."

        # Auto-build skills in background if auto-apply is enabled
        if auto_apply_enabled and background_tasks:
            log.info(f"Auto-apply enabled: triggering skill building for {len(gaps)} gaps")
            background_tasks.add_task(
                _run_autonomous_skill_building,
                challenge_id=challenge_id,
                gaps=[g.model_dump() for g in gaps],
            )
            message += " Auto-building skills in background..."

    log.info(f"File upload: {file.filename} -> challenge_id={challenge_id}, gaps={len(gaps)}, route={route_decision}")

    return ChallengeAnalysisWithPlanResponse(
        challenge_id=challenge_id,
        assessment=assessment.model_dump(),
        challenge_text=file_info[:500] + "..." if len(file_info) > 500 else file_info,
        execution_id=execution_id,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        route_decision=route_decision,
        build_plan=build_plan_dict,
        build_plan_status=challenge.build_plan_status if build_plan_dict else None,
        auto_apply_enabled=auto_apply_enabled,
        message=message,
    )


@router.get("/blocked")
async def get_blocked_challenges(
    include_resolved: bool = Query(False, description="Include resolved/failed/cancelled challenges"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get blocked challenges from the intervention queue.

    By default returns only active (non-terminal) challenges.
    """
    log.info(f"Getting blocked challenges: include_resolved={include_resolved}")

    stmt = select(BlockedChallenge).order_by(BlockedChallenge.created_at.desc())

    if not include_resolved:
        active_statuses = ["queued", "building", "built", "injected"]
        stmt = stmt.where(BlockedChallenge.status.in_(active_statuses))

    result = await session.execute(stmt)
    challenges = list(result.scalars().all())

    return [
        {
            "id": c.id,
            "execution_id": c.execution_id,
            "project_id": c.project_id,
            "challenge_text": c.challenge_text,
            "assessment_result": c.assessment_result,
            "gaps_snapshot": c.gaps_snapshot,
            "status": c.status,
            "attempt_number": c.attempt_number,
            "max_attempts": c.max_attempts,
            "built_capability_ids": c.built_capability_ids or [],
            "execution_results": c.execution_results,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
            "failure_reasons": c.failure_reasons or [],
        }
        for c in challenges
    ]


@router.post("", response_model=ChallengeCreateResponse)
async def submit_challenge(
    challenge_text: str = Form(None, description="Challenge text"),
    file: UploadFile = File(None, description="Challenge file"),
    project_id: str = Form("default", description="Project ID"),
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeCreateResponse:
    """
    Submit a new challenge (text or file).

    Either challenge_text or file must be provided.
    Creates a new challenge record and returns its ID for tracking.
    """
    log.info(f"Submitting challenge: has_text={challenge_text is not None}, has_file={file is not None}")

    # Extract challenge text from file if provided
    if file and not challenge_text:
        content = await file.read()
        try:
            challenge_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="File must be UTF-8 encoded text"
            )

    if not challenge_text:
        raise HTTPException(
            status_code=400,
            detail="Either challenge_text or file must be provided"
        )

    # Generate IDs
    challenge_id = str(uuid.uuid4())
    execution_id = str(uuid.uuid4())

    # Create blocked challenge record (initially in queued state)
    # This will be used for tracking the challenge lifecycle
    challenge = BlockedChallenge(
        id=challenge_id,
        execution_id=execution_id,
        project_id=project_id,
        challenge_text=challenge_text,
        assessment_result={},  # Will be filled during analysis
        gaps_snapshot=[],
        status="queued",
    )

    session.add(challenge)
    await session.commit()
    await session.refresh(challenge)

    return ChallengeCreateResponse(
        id=challenge.id,
        execution_id=challenge.execution_id,
        challenge_text=challenge_text[:200] + "..." if len(challenge_text) > 200 else challenge_text,
        status=challenge.status,
        created_at=challenge.created_at.isoformat() if challenge.created_at else datetime.now(timezone.utc).isoformat(),
    )


@router.post("/{challenge_id}/analyze", response_model=ChallengeAssessmentResponse)
async def analyze_challenge(
    challenge_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeAssessmentResponse:
    """
    Trigger capability assessment for a challenge.

    Analyzes the challenge to determine if the system can handle it.
    Returns confidence level and any capability gaps.
    """
    log.info(f"Analyzing challenge: id={challenge_id}")

    # Get challenge
    stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
    result = await session.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail=f"Challenge not found: {challenge_id}")

    # Perform capability assessment using PreExecutionOrchestrator
    try:
        embedding_fn = create_embedding_fn()
        structured_llm_fn = create_structured_llm_fn()
        orchestrator = await create_pre_execution_orchestrator(
            db=session,
            embedding_fn=embedding_fn,
            structured_llm_fn=structured_llm_fn,
        )

        # Build analysis request from stored challenge
        analysis_request = ChallengeAnalysisRequest(
            challenge_text=challenge.challenge_text,
            execution_id=challenge.execution_id,
            project_id=challenge.project_id or "default",
            include_cross_project=True
        )

        # Run the orchestrator analysis
        analysis_response = await orchestrator.analyze_challenge(analysis_request)
        assessment = analysis_response.assessment
        route_decision = analysis_response.route_decision

        log.info(f"Orchestrator analysis complete: confidence={assessment.confidence.value}, route={route_decision}")

    except Exception as e:
        log.error(f"Orchestrator analysis failed, using fallback: {e}")
        # Fallback to simple assessment if orchestrator fails
        assessment = CapabilityAssessment(
            confidence=ConfidenceLevel.CAN_DO,
            reasoning=f"Fallback assessment (orchestrator error: {str(e)[:100]})",
            top_factors=["Fallback mode active"],
            gaps=[],
            improvement_suggestions=[],
            similar_past_success=False,
        )
        route_decision = "execute"

    # Update challenge with assessment
    challenge.assessment_result = assessment.model_dump()
    challenge.gaps_snapshot = [g.model_dump() for g in assessment.gaps]
    await session.commit()

    return ChallengeAssessmentResponse(
        challenge_id=challenge_id,
        execution_id=challenge.execution_id,
        confidence=assessment.confidence.value,
        reasoning=assessment.reasoning,
        top_factors=assessment.top_factors,
        gaps=[g.model_dump() for g in assessment.gaps],
        improvement_suggestions=assessment.improvement_suggestions,
        route_decision=route_decision,
        assessed_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{challenge_id}/assessment", response_model=ChallengeAssessmentResponse)
async def get_assessment(
    challenge_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeAssessmentResponse:
    """
    Get assessment result for a challenge.

    Returns 404 if challenge not found or not yet assessed.
    """
    log.info(f"Getting assessment: challenge_id={challenge_id}")

    # Get challenge
    stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
    result = await session.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail=f"Challenge not found: {challenge_id}")

    if not challenge.assessment_result:
        raise HTTPException(status_code=404, detail=f"Challenge not yet assessed: {challenge_id}")

    # Parse assessment from stored dict
    assessment_dict = challenge.assessment_result
    confidence = ConfidenceLevel(assessment_dict.get("confidence", "CAN_DO"))
    route_decision = "developer_team" if confidence in (ConfidenceLevel.MAYBE, ConfidenceLevel.CANNOT_DO) else "execute"

    return ChallengeAssessmentResponse(
        challenge_id=challenge_id,
        execution_id=challenge.execution_id,
        confidence=confidence.value,
        reasoning=assessment_dict.get("reasoning", ""),
        top_factors=assessment_dict.get("top_factors", []),
        gaps=challenge.gaps_snapshot or [],
        improvement_suggestions=assessment_dict.get("improvement_suggestions", []),
        route_decision=route_decision,
        assessed_at=challenge.updated_at.isoformat() if challenge.updated_at else "",
    )


@router.post("/{challenge_id}/execute", response_model=ChallengeExecutionResponse)
async def execute_challenge(
    challenge_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeExecutionResponse:
    """
    Start execution of a challenge.

    Requires challenge to be assessed first with CAN_DO confidence,
    or to have had capabilities built by Developer Team.

    Execution runs asynchronously via HybridOrchestrator.
    Results are stored in challenge.execution_results and accessible via GET /challenges/{id}/results.
    """
    log.info(f"Executing challenge: id={challenge_id}")

    # Get challenge
    stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
    result = await session.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail=f"Challenge not found: {challenge_id}")

    # Check assessment
    if not challenge.assessment_result:
        raise HTTPException(
            status_code=400,
            detail="Challenge must be assessed before execution. Call /analyze first."
        )

    # Update status to executing
    challenge.status = "executing"
    await session.commit()

    # Run orchestrator execution in background
    background_tasks.add_task(
        _run_challenge_execution,
        challenge_id=challenge_id,
        execution_id=challenge.execution_id,
        project_id=challenge.project_id,
        challenge_text=challenge.challenge_text,
    )

    return ChallengeExecutionResponse(
        challenge_id=challenge_id,
        execution_id=challenge.execution_id,
        status=challenge.status,
        message="Execution started",
        started_at=datetime.now(timezone.utc).isoformat(),
    )


async def _run_challenge_execution(
    challenge_id: str,
    execution_id: str,
    project_id: str,
    challenge_text: str,
) -> None:
    """
    Background task to run orchestrator execution.

    Creates its own database session and orchestrator instance
    to avoid session lifecycle issues with background tasks.
    """
    from app.dependencies.dependencies import AsyncSessionLocal
    from app.core.llm_client import LLMClient
    from app.orchestration.orchestrators.hybrid_orchestrator import HybridOrchestrator

    log.info(f"Starting background execution: challenge_id={challenge_id}")

    async with AsyncSessionLocal() as session:
        try:
            # Initialize orchestrator
            llm = LLMClient()
            orchestrator = HybridOrchestrator(db=session, llm_client=llm)
            await orchestrator.initialize()

            # Execute via orchestrator
            results = await orchestrator.execute(
                input_data={"challenge": challenge_text},
                execution_id=execution_id,
                project_id=project_id,
                challenge_id=challenge_id,
            )

            # Update challenge with results
            stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
            result = await session.execute(stmt)
            challenge = result.scalar_one_or_none()

            if challenge:
                if results.get("success"):
                    challenge.status = "resolved"
                    challenge.resolved_at = datetime.now(timezone.utc)
                else:
                    challenge.status = "failed"
                    failure_reasons = challenge.failure_reasons or []
                    failure_reasons.append(results.get("error", "Unknown error"))
                    challenge.failure_reasons = failure_reasons

                challenge.execution_results = results
                await session.commit()

            log.info(f"Execution completed: challenge_id={challenge_id}, success={results.get('success')}")

        except Exception as e:
            log.error(f"Execution failed: challenge_id={challenge_id}, error={e}")

            # Update challenge status to failed
            stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
            result = await session.execute(stmt)
            challenge = result.scalar_one_or_none()

            if challenge:
                challenge.status = "failed"
                failure_reasons = challenge.failure_reasons or []
                failure_reasons.append(str(e))
                challenge.failure_reasons = failure_reasons
                challenge.execution_results = {"success": False, "error": str(e)}
                await session.commit()


@router.get("/{challenge_id}", response_model=ChallengeStatusResponse)
async def get_challenge_status(
    challenge_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeStatusResponse:
    """
    Get current status of a challenge.

    Returns full challenge state including assessment and capabilities.
    """
    log.info(f"Getting challenge status: id={challenge_id}")

    # Get challenge
    stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
    result = await session.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail=f"Challenge not found: {challenge_id}")

    return ChallengeStatusResponse(
        id=challenge.id,
        execution_id=challenge.execution_id,
        challenge_text=challenge.challenge_text[:500] + "..." if len(challenge.challenge_text) > 500 else challenge.challenge_text,
        status=challenge.status,
        attempt_number=challenge.attempt_number,
        max_attempts=challenge.max_attempts,
        assessment_result=challenge.assessment_result,
        gaps_snapshot=challenge.gaps_snapshot or [],
        built_capability_ids=challenge.built_capability_ids or [],
        execution_results=challenge.execution_results,
        created_at=challenge.created_at.isoformat() if challenge.created_at else "",
        updated_at=challenge.updated_at.isoformat() if challenge.updated_at else None,
        resolved_at=challenge.resolved_at.isoformat() if challenge.resolved_at else None,
    )


@router.get("/{challenge_id}/results", response_model=ChallengeResultsResponse)
async def get_challenge_results(
    challenge_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeResultsResponse:
    """
    Get execution results for a challenge.

    Returns the orchestrator output after execution completes.
    Returns 404 if challenge not found, 400 if not yet executed.
    """
    log.info(f"Getting challenge results: id={challenge_id}")

    # Get challenge
    stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
    result = await session.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail=f"Challenge not found: {challenge_id}")

    if challenge.status in ("queued", "assessed", "analyzing"):
        raise HTTPException(
            status_code=400,
            detail=f"Challenge not yet executed. Current status: {challenge.status}"
        )

    execution_results = challenge.execution_results or {}

    return ChallengeResultsResponse(
        challenge_id=challenge_id,
        execution_id=challenge.execution_id,
        status=challenge.status,
        execution_results=execution_results,
        duration_ms=execution_results.get("duration_ms"),
        agents_executed=execution_results.get("agents_executed", 0),
        completed_at=challenge.resolved_at.isoformat() if challenge.resolved_at else None,
    )


@router.get("/by-execution/{execution_id}", response_model=ChallengeStatusResponse)
async def get_challenge_by_execution_id(
    execution_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ChallengeStatusResponse:
    """
    Get challenge by its execution ID.

    Useful for polling status from the execution detail page.
    """
    log.info(f"Getting challenge by execution_id: {execution_id}")

    # Get challenge by execution_id
    stmt = select(BlockedChallenge).where(BlockedChallenge.execution_id == execution_id)
    result = await session.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail=f"Challenge not found for execution: {execution_id}")

    return ChallengeStatusResponse(
        id=challenge.id,
        execution_id=challenge.execution_id,
        challenge_text=challenge.challenge_text[:500] + "..." if len(challenge.challenge_text) > 500 else challenge.challenge_text,
        status=challenge.status,
        attempt_number=challenge.attempt_number,
        max_attempts=challenge.max_attempts,
        assessment_result=challenge.assessment_result,
        gaps_snapshot=challenge.gaps_snapshot or [],
        built_capability_ids=challenge.built_capability_ids or [],
        execution_results=challenge.execution_results,
        created_at=challenge.created_at.isoformat() if challenge.created_at else "",
        updated_at=challenge.updated_at.isoformat() if challenge.updated_at else None,
        resolved_at=challenge.resolved_at.isoformat() if challenge.resolved_at else None,
    )


# ============================================================================
# Build Plan Endpoints
# ============================================================================

@router.get("/{challenge_id}/build-plan", response_model=BuildPlanResponse)
async def get_build_plan(
    challenge_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> BuildPlanResponse:
    """
    Get the build plan for a challenge.

    Returns the generated build plan with current status.
    """
    log.info(f"Getting build plan: challenge_id={challenge_id}")

    stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
    result = await session.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail=f"Challenge not found: {challenge_id}")

    if not challenge.build_plan:
        raise HTTPException(status_code=404, detail="No build plan exists for this challenge")

    # Get auto-apply setting
    build_plan_service = BuildPlanService(session)
    auto_apply = await build_plan_service.is_auto_apply_enabled()

    return BuildPlanResponse(
        plan=BuildPlan(**challenge.build_plan),
        status=BuildPlanStatus(challenge.build_plan_status or "pending"),
        auto_apply_enabled=auto_apply,
        message=f"Plan has {len(challenge.build_plan.get('items', []))} items to build",
    )


@router.post("/{challenge_id}/build-plan/approve")
async def approve_build_plan(
    challenge_id: str,
    request: BuildPlanApprovalRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Approve or reject a build plan.

    If approved, triggers InterventionOrchestrator to build capabilities.
    """
    log.info(f"Build plan approval: challenge_id={challenge_id}, approved={request.approved}")

    stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
    result = await session.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail=f"Challenge not found: {challenge_id}")

    if not challenge.build_plan:
        raise HTTPException(status_code=400, detail="No build plan to approve")

    if challenge.build_plan_status not in ("pending", None):
        raise HTTPException(
            status_code=400,
            detail=f"Plan already processed: {challenge.build_plan_status}"
        )

    if request.approved:
        challenge.build_plan_status = BuildPlanStatus.APPROVED.value
        await session.commit()

        # Trigger capability building in background
        background_tasks.add_task(
            _run_capability_building,
            challenge_id=challenge_id,
        )

        return {
            "status": "approved",
            "message": "Build-Plan genehmigt. Capabilities werden gebaut...",
            "challenge_id": challenge_id,
        }
    else:
        challenge.build_plan_status = BuildPlanStatus.REJECTED.value
        if request.feedback:
            # Store feedback for future improvements
            failure_reasons = challenge.failure_reasons or []
            failure_reasons.append(f"User rejected: {request.feedback}")
            challenge.failure_reasons = failure_reasons
        await session.commit()

        return {
            "status": "rejected",
            "message": "Build-Plan abgelehnt.",
            "challenge_id": challenge_id,
        }


async def _run_capability_building(challenge_id: str) -> None:
    """
    Background task to build capabilities via InterventionOrchestrator.

    This runs the full intervention lifecycle:
    1. Build capabilities for each gap
    2. Inject into topology
    3. Re-assess
    4. Execute if CAN_DO
    """
    from app.dependencies.dependencies import AsyncSessionLocal
    from app.orchestration.intervention.orchestrator import create_intervention_orchestrator
    from app.core.llm_client import create_llm_fn, create_embedding_fn, create_structured_llm_fn

    log.info(f"Starting capability building: challenge_id={challenge_id}")

    async with AsyncSessionLocal() as session:
        try:
            # Get challenge
            stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
            result = await session.execute(stmt)
            challenge = result.scalar_one_or_none()

            if not challenge:
                log.error(f"Challenge not found for building: {challenge_id}")
                return

            # Update status
            challenge.build_plan_status = BuildPlanStatus.IN_PROGRESS.value
            challenge.status = "building"
            await session.commit()

            # Create LLM and embedding functions for capability matching
            llm_fn = create_llm_fn()
            embedding_fn = create_embedding_fn()
            structured_llm_fn = create_structured_llm_fn()

            # Create intervention orchestrator with LLM and embedding support
            orchestrator = await create_intervention_orchestrator(
                db=session,
                llm_fn=llm_fn,
                embedding_fn=embedding_fn,
                structured_llm_fn=structured_llm_fn,
            )

            # Process the challenge
            intervention_result = await orchestrator.process_blocked_challenge(challenge)

            # Update based on result
            if intervention_result.route_decision == "execute":
                challenge.build_plan_status = BuildPlanStatus.COMPLETED.value
                challenge.status = "resolved"
                challenge.resolved_at = datetime.now(timezone.utc)
                log.info(f"Capability building successful: {challenge_id}")
            else:
                challenge.build_plan_status = BuildPlanStatus.FAILED.value
                challenge.status = "failed" if intervention_result.route_decision == "failed" else "queued"
                log.warning(f"Capability building incomplete: {challenge_id}, decision={intervention_result.route_decision}")

            await session.commit()

        except Exception as e:
            log.error(f"Capability building failed: challenge_id={challenge_id}, error={e}")

            # Update status to failed
            stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
            result = await session.execute(stmt)
            challenge = result.scalar_one_or_none()

            if challenge:
                challenge.build_plan_status = BuildPlanStatus.FAILED.value
                challenge.status = "failed"
                failure_reasons = challenge.failure_reasons or []
                failure_reasons.append(str(e))
                challenge.failure_reasons = failure_reasons
                await session.commit()


# ============================================================================
# User Settings Endpoints
# ============================================================================

@router.get("/settings/user", response_model=UserSettingsResponse)
async def get_user_settings(
    session: AsyncSession = Depends(get_db_session),
) -> UserSettingsResponse:
    """
    Get current user settings including auto-apply preference.
    """
    build_plan_service = BuildPlanService(session)
    settings = await build_plan_service.get_user_settings()

    return UserSettingsResponse(
        auto_apply=settings.auto_apply,
        notify_on_build=settings.notify_on_build,
        notify_on_execution=settings.notify_on_execution,
    )


@router.put("/settings/user", response_model=UserSettingsResponse)
async def update_user_settings(
    request: UserSettingsUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> UserSettingsResponse:
    """
    Update user settings.

    Toggle auto_apply to enable/disable automatic capability building.
    """
    log.info(f"Updating user settings: auto_apply={request.auto_apply}")

    build_plan_service = BuildPlanService(session)
    settings = await build_plan_service.update_user_settings(
        auto_apply=request.auto_apply,
        notify_on_build=request.notify_on_build,
        notify_on_execution=request.notify_on_execution,
    )

    return UserSettingsResponse(
        auto_apply=settings.auto_apply,
        notify_on_build=settings.notify_on_build,
        notify_on_execution=settings.notify_on_execution,
    )


# ============================================================================
# Autonomous Skill Building Endpoints
# ============================================================================

class SkillBuildRequest(BaseModel):
    """Request to build a skill for a capability."""
    capability: str = Field(..., description="Capability to build (e.g., 'audio transcription')")
    hints: Optional[dict] = Field(None, description="Optional hints for packages")


class SkillBuildResponse(BaseModel):
    """Response from skill building."""
    success: bool
    skill_id: Optional[str] = None
    skill_name: Optional[str] = None
    iterations: int = 0
    pip_requirements: list[str] = []
    system_packages: list[str] = []
    error: Optional[str] = None
    message: str = ""


@router.post("/{challenge_id}/build-skills", response_model=SkillBuildResponse)
async def build_skills_for_challenge(
    challenge_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> SkillBuildResponse:
    """
    Trigger autonomous skill building for a challenge's capability gaps.

    The system will:
    1. Research how to implement each missing capability
    2. Generate and test code in a sandbox
    3. Iterate on errors until success (max 5 attempts)
    4. Persist successful skills to database

    This is the OpenClaw-style self-improvement endpoint.
    """
    log.info(f"Building skills for challenge: {challenge_id}")

    # Get challenge
    result = await session.execute(
        select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if not challenge.gaps_snapshot:
        return SkillBuildResponse(
            success=True,
            message="No capability gaps to build skills for",
        )

    # Get first gap to build
    gaps = challenge.gaps_snapshot
    first_gap = gaps[0] if gaps else None

    if not first_gap:
        return SkillBuildResponse(
            success=True,
            message="No gaps found",
        )

    capability = first_gap.get("affected_capability", "unknown")
    log.info(f"Building skill for capability: {capability}")

    # Build skill autonomously
    builder = AutonomousSkillBuilder(session)
    build_result = await builder.build_skill(
        capability=capability,
        test_input={},  # Basic test
    )

    if build_result.success:
        # Update challenge status
        challenge.status = "skills_built"
        challenge.built_capability_ids = [build_result.skill_id]
        await session.commit()

        # Get skill metadata
        skill_meta = build_result.skill.skill_metadata if build_result.skill else {}

        return SkillBuildResponse(
            success=True,
            skill_id=build_result.skill_id,
            skill_name=build_result.skill.name if build_result.skill else None,
            iterations=build_result.iterations,
            pip_requirements=skill_meta.get("pip_requirements", []),
            system_packages=skill_meta.get("system_packages", []),
            message=f"Skill built successfully in {build_result.iterations} iteration(s)",
        )
    else:
        return SkillBuildResponse(
            success=False,
            iterations=build_result.iterations,
            error=build_result.final_error,
            message=f"Failed to build skill after {build_result.iterations} attempts",
        )


async def _run_autonomous_skill_building(
    challenge_id: str,
    gaps: list[dict],
) -> None:
    """
    Background task to autonomously build skills for capability gaps.

    This is the heart of the self-improving system:
    1. For each gap, research and build a skill
    2. Test skills in sandbox with pip/apt packages
    3. Iterate on errors (max 5 attempts per skill)
    4. **USE the skill to process the original file**
    5. Cache successful container images for future use
    """
    from app.dependencies.dependencies import AsyncSessionLocal
    from app.services.autonomous_skill_builder import AutonomousSkillBuilder
    import os
    import re

    log.info(f"Starting autonomous skill building: challenge_id={challenge_id}, gaps={len(gaps)}")

    async with AsyncSessionLocal() as session:
        try:
            # Get challenge
            stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
            result = await session.execute(stmt)
            challenge = result.scalar_one_or_none()

            if not challenge:
                log.error(f"Challenge not found: {challenge_id}")
                return

            # Extract file path from challenge text (if binary file was uploaded)
            file_path = None
            file_path_match = re.search(r'Storage Path: (.+)', challenge.challenge_text)
            if file_path_match:
                file_path = file_path_match.group(1).strip()
                log.info(f"Found uploaded file: {file_path}")

            # Update status
            challenge.status = "building_skills"
            await session.commit()

            # Create skill builder
            builder = AutonomousSkillBuilder(db=session)

            built_skill_ids = []
            failed_capabilities = []
            processing_results = []

            for gap in gaps:
                capability = gap.get("affected_capability", "unknown")
                log.info(f"Building skill for: {capability}")

                try:
                    # Prepare test input - include file path if available
                    test_input = {}
                    input_files = {}

                    if file_path and os.path.exists(file_path):
                        test_input["file_path"] = f"/workspace/{os.path.basename(file_path)}"
                        with open(file_path, "rb") as f:
                            input_files[os.path.basename(file_path)] = f.read()

                    # Build the skill
                    build_result = await builder.build_skill(
                        capability=capability,
                        test_input=test_input if test_input else {"test": True},
                        input_files=input_files if input_files else None,
                    )

                    if build_result.success and build_result.skill_id:
                        built_skill_ids.append(build_result.skill_id)
                        log.info(f"Successfully built skill: {build_result.skill_id}")

                        # NOW USE THE SKILL to process the original file
                        if file_path and os.path.exists(file_path) and build_result.skill:
                            log.info(f"Using new skill to process: {file_path}")
                            try:
                                executor = AutonomousExecutorService(db=session)
                                skill_meta = build_result.skill.skill_metadata or {}

                                # Get requirements from metadata, with fallback detection
                                pip_requirements = skill_meta.get("pip_requirements", [])
                                system_packages = skill_meta.get("system_packages", [])

                                # Ensure requirements are detected if metadata is incomplete
                                if not pip_requirements:
                                    pip_requirements = _detect_pip_requirements(
                                        build_result.skill.code, capability
                                    )
                                    log.info(f"Auto-detected pip requirements: {pip_requirements}")
                                if not system_packages:
                                    system_packages = _detect_system_packages(capability)
                                    log.info(f"Auto-detected system packages: {system_packages}")

                                exec_result = await executor.execute_skill(
                                    code=build_result.skill.code,
                                    function_name="execute",
                                    arguments={"file_path": f"/workspace/{os.path.basename(file_path)}"},
                                    pip_requirements=pip_requirements,
                                    system_packages=system_packages,
                                    input_files=input_files,
                                )

                                if exec_result.success:
                                    processing_results.append({
                                        "capability": capability,
                                        "result": exec_result.output,
                                        "success": True,
                                    })
                                    log.info(f"File processed successfully: {exec_result.output}")

                                    # Update challenge text with the result (e.g., transcription)
                                    if capability == "audio transcription" and exec_result.output:
                                        transcript = exec_result.output.get("text") or exec_result.output.get("result") or str(exec_result.output)
                                        challenge.challenge_text = f"""[TRANSCRIBED AUDIO FILE]
Original File: {os.path.basename(file_path)}
Transcription Method: Auto-built Skill (faster-whisper)

[TRANSCRIPTION]
{transcript}

[TASK]
Analyze the above transcribed content.
"""
                                else:
                                    log.warning(f"File processing failed: {exec_result.error}")
                                    processing_results.append({
                                        "capability": capability,
                                        "error": exec_result.error,
                                        "success": False,
                                    })
                            except Exception as proc_err:
                                log.error(f"Error processing file with skill: {proc_err}")
                    else:
                        failed_capabilities.append(capability)
                        log.warning(f"Failed to build skill for: {capability}")

                except Exception as e:
                    log.error(f"Error building skill for {capability}: {e}")
                    failed_capabilities.append(capability)

            # Update challenge with results
            challenge.built_capability_ids = built_skill_ids

            if len(built_skill_ids) == len(gaps):
                challenge.status = "ready"
                challenge.build_plan_status = BuildPlanStatus.COMPLETED.value
                log.info(f"All {len(gaps)} skills built successfully")
            elif built_skill_ids:
                challenge.status = "partially_ready"
                log.info(f"Built {len(built_skill_ids)}/{len(gaps)} skills")
            else:
                challenge.status = "build_failed"
                challenge.build_plan_status = BuildPlanStatus.FAILED.value
                log.error(f"Failed to build any skills")

            # Store processing results
            if processing_results:
                challenge.execution_results = {
                    "processing_results": processing_results,
                    "skills_built": len(built_skill_ids),
                    "auto_processed": True,
                }

            await session.commit()
            log.info(f"Skill building complete: {len(built_skill_ids)} built, {len(failed_capabilities)} failed")

        except Exception as e:
            log.error(f"Autonomous skill building failed: {e}")

            # Session may be in a broken state — rollback before retrying
            try:
                await session.rollback()
            except Exception:
                pass

            try:
                stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
                result = await session.execute(stmt)
                challenge = result.scalar_one_or_none()

                if challenge:
                    challenge.status = "build_failed"
                    challenge.build_plan_status = BuildPlanStatus.FAILED.value
                    failure_reasons = challenge.failure_reasons or []
                    failure_reasons.append(f"Autonomous build failed: {str(e)}")
                    challenge.failure_reasons = failure_reasons
                    await session.commit()
            except Exception as recovery_err:
                log.error(f"Failed to update challenge status after error: {recovery_err}")


@router.post("/build-skill", response_model=SkillBuildResponse)
async def build_skill_directly(
    request: SkillBuildRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SkillBuildResponse:
    """
    Build a skill for any capability directly.

    Use this to proactively build skills before they're needed.

    Example:
        POST /challenges/build-skill
        {"capability": "pdf reading", "hints": {"pip": ["pypdf"]}}
    """
    log.info(f"Direct skill build request: {request.capability}")

    builder = AutonomousSkillBuilder(session)
    build_result = await builder.build_skill(
        capability=request.capability,
        hints=request.hints,
        test_input={},
    )

    if build_result.success:
        skill_meta = build_result.skill.skill_metadata if build_result.skill else {}

        return SkillBuildResponse(
            success=True,
            skill_id=build_result.skill_id,
            skill_name=build_result.skill.name if build_result.skill else None,
            iterations=build_result.iterations,
            pip_requirements=skill_meta.get("pip_requirements", []),
            system_packages=skill_meta.get("system_packages", []),
            message=f"Skill '{request.capability}' built successfully",
        )
    else:
        return SkillBuildResponse(
            success=False,
            iterations=build_result.iterations,
            error=build_result.final_error,
            message=f"Failed to build skill for '{request.capability}'",
        )


# ============================================================================
# Monitoring & Metrics Endpoints (Phase 4)
# ============================================================================

class ExecutorMetricsResponse(BaseModel):
    """Execution metrics for monitoring."""
    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float
    skills_auto_built: int
    avg_execution_time_ms: float


class CacheStatsResponse(BaseModel):
    """Container cache statistics."""
    total_images: int
    ready_images: int
    error_images: int
    building_images: int
    total_size_mb: float
    total_usage_count: int
    by_capability: dict


class SystemHealthResponse(BaseModel):
    """System health status."""
    status: str  # healthy, degraded, unhealthy
    docker_available: bool
    database_connected: bool
    executor_metrics: ExecutorMetricsResponse
    cache_stats: Optional[CacheStatsResponse] = None
    timestamp: str


@router.get("/metrics/executor", response_model=ExecutorMetricsResponse)
async def get_executor_metrics(
    session: AsyncSession = Depends(get_db_session),
) -> ExecutorMetricsResponse:
    """
    Get execution metrics for the autonomous executor.

    Returns statistics about skill executions, cache hits, and auto-builds.
    """
    executor = AutonomousExecutorService(db=session)
    metrics = executor.get_metrics()

    return ExecutorMetricsResponse(
        total_executions=metrics["total_executions"],
        successful_executions=metrics["successful_executions"],
        failed_executions=metrics["failed_executions"],
        success_rate=metrics["success_rate"],
        cache_hits=metrics["cache_hits"],
        cache_misses=metrics["cache_misses"],
        cache_hit_rate=metrics["cache_hit_rate"],
        skills_auto_built=metrics["skills_auto_built"],
        avg_execution_time_ms=metrics["avg_execution_time_ms"],
    )


@router.get("/metrics/cache", response_model=CacheStatsResponse)
async def get_cache_stats(
    session: AsyncSession = Depends(get_db_session),
) -> CacheStatsResponse:
    """
    Get container image cache statistics.

    Returns information about cached Docker images.
    """
    executor = AutonomousExecutorService(db=session)
    stats = await executor.get_cache_stats()

    if not stats.get("caching_enabled", True):
        raise HTTPException(status_code=400, detail="Container caching is disabled")

    return CacheStatsResponse(
        total_images=stats.get("total_images", 0),
        ready_images=stats.get("ready_images", 0),
        error_images=stats.get("error_images", 0),
        building_images=stats.get("building_images", 0),
        total_size_mb=stats.get("total_size_mb", 0),
        total_usage_count=stats.get("total_usage_count", 0),
        by_capability=stats.get("by_capability", {}),
    )


@router.get("/metrics/health", response_model=SystemHealthResponse)
async def get_system_health(
    session: AsyncSession = Depends(get_db_session),
) -> SystemHealthResponse:
    """
    Get overall system health status.

    Checks Docker, database, and executor status.
    """
    from app.services.dynamic_sandbox_service import DynamicSandboxService

    # Check Docker
    sandbox = DynamicSandboxService()
    docker_available = sandbox.is_available()

    # Check database (we're already connected if we got here)
    database_connected = True

    # Get executor metrics
    executor = AutonomousExecutorService(db=session)
    metrics = executor.get_metrics()

    # Get cache stats (if available)
    cache_stats = None
    try:
        stats = await executor.get_cache_stats()
        if stats.get("caching_enabled", True):
            cache_stats = CacheStatsResponse(
                total_images=stats.get("total_images", 0),
                ready_images=stats.get("ready_images", 0),
                error_images=stats.get("error_images", 0),
                building_images=stats.get("building_images", 0),
                total_size_mb=stats.get("total_size_mb", 0),
                total_usage_count=stats.get("total_usage_count", 0),
                by_capability=stats.get("by_capability", {}),
            )
    except Exception:
        pass

    # Determine overall status
    if docker_available and database_connected:
        status = "healthy"
    elif docker_available or database_connected:
        status = "degraded"
    else:
        status = "unhealthy"

    return SystemHealthResponse(
        status=status,
        docker_available=docker_available,
        database_connected=database_connected,
        executor_metrics=ExecutorMetricsResponse(
            total_executions=metrics["total_executions"],
            successful_executions=metrics["successful_executions"],
            failed_executions=metrics["failed_executions"],
            success_rate=metrics["success_rate"],
            cache_hits=metrics["cache_hits"],
            cache_misses=metrics["cache_misses"],
            cache_hit_rate=metrics["cache_hit_rate"],
            skills_auto_built=metrics["skills_auto_built"],
            avg_execution_time_ms=metrics["avg_execution_time_ms"],
        ),
        cache_stats=cache_stats,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/cache/cleanup")
async def cleanup_cache(
    max_age_days: int = 7,
    max_unused_days: int = 3,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Clean up old/unused cached container images.

    Args:
        max_age_days: Remove images older than this
        max_unused_days: Remove images not used in this many days
    """
    executor = AutonomousExecutorService(db=session)
    removed_count = await executor.cleanup_old_images(
        max_age_days=max_age_days,
        max_unused_days=max_unused_days,
    )

    return {
        "success": True,
        "removed_images": removed_count,
        "message": f"Cleaned up {removed_count} cached images",
    }
