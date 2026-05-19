"""
Pydantic schemas for team-based skill development.

Defines the data structures for:
- Team roles and configurations
- Research contexts
- Architecture designs
- Code reviews
- Build results
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class TeamRole(str, Enum):
    """Roles in the skill development team."""
    RESEARCHER = "researcher"     # Researches solutions, finds packages, examples
    ARCHITECT = "architect"       # Designs API, test cases, dependencies
    IMPLEMENTER = "implementer"   # Writes the actual code
    REVIEWER = "reviewer"         # Reviews code for quality, security
    PROPOSER = "proposer"         # Proposes planning-skills (reasoning instructions)
    TESTER = "tester"             # Runs tests, validates output


class ErrorType(str, Enum):
    """Classification of errors for learning."""
    IMPORT_ERROR = "import_error"       # Missing module/package
    SYNTAX_ERROR = "syntax_error"       # Invalid Python syntax
    RUNTIME_ERROR = "runtime_error"     # Exception during execution
    SEMANTIC_ERROR = "semantic_error"   # Wrong output/behavior
    TIMEOUT_ERROR = "timeout_error"     # Execution took too long
    RESOURCE_ERROR = "resource_error"   # OOM, disk full, etc.
    DEPENDENCY_ERROR = "dependency_error"  # Package conflict, version issue
    STRUCTURE_ERROR = "structure_error"    # Missing execute(), wrong signature


class SkillTeamConfig(BaseModel):
    """Configuration for team-based skill development."""
    model_config = ConfigDict(frozen=True)

    # Team composition
    enable_researcher: bool = Field(default=True, description="Enable research phase")
    enable_architect: bool = Field(default=True, description="Enable architecture design")
    enable_reviewer: bool = Field(default=True, description="Enable code review")

    # Model assignments (can be overridden per role)
    researcher_model: Optional[str] = Field(default=None, description="Model for researcher role")
    architect_model: Optional[str] = Field(default=None, description="Model for architect role")
    implementer_model: Optional[str] = Field(default=None, description="Model for implementer role")
    reviewer_model: Optional[str] = Field(default=None, description="Model for reviewer role")

    # Iteration limits
    max_implementation_iterations: int = Field(default=10, ge=1, le=10)
    max_review_iterations: int = Field(default=2, ge=1, le=5)

    # Validation
    require_semantic_validation: bool = Field(default=True)
    semantic_similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class ResearchContext(BaseModel):
    """Context gathered during research phase."""
    capability: str = Field(..., description="The capability being researched")
    query: str = Field(default="", description="Search query used")

    # Package recommendations
    pip_packages: list[str] = Field(default_factory=list, description="Recommended pip packages")
    system_packages: list[str] = Field(default_factory=list, description="Recommended apt packages")
    package_rationale: dict[str, str] = Field(
        default_factory=dict,
        description="Why each package was recommended"
    )

    # Code examples
    code_examples: list[str] = Field(default_factory=list, description="Example implementations")
    example_sources: list[str] = Field(default_factory=list, description="Sources of examples")

    # Implementation notes
    implementation_approach: str = Field(default="", description="Recommended approach")
    potential_issues: list[str] = Field(default_factory=list, description="Known issues to watch for")
    alternative_approaches: list[str] = Field(default_factory=list, description="Fallback approaches")

    # Similar past solutions
    similar_skills: list[dict] = Field(default_factory=list, description="Similar successful skills")

    # Metadata
    from_cache: bool = Field(default=False, description="Whether from cache")
    research_time_ms: int = Field(default=0, ge=0)


class TestCase(BaseModel):
    """A test case for skill validation."""
    name: str = Field(..., description="Test case name")
    input_data: dict = Field(default_factory=dict, description="Input to the skill")
    expected_output: Optional[Any] = Field(default=None, description="Expected output value")
    expected_output_type: str = Field(default="any", description="Expected output type")
    expected_keys: list[str] = Field(default_factory=list, description="Keys that must be in output dict")
    timeout_seconds: int = Field(default=60, ge=1)


class SkillIntegrationPlan(BaseModel):
    """Architect's plan for where and how a skill integrates into the agent topology."""
    target_agent_id: Optional[str] = Field(default=None, description="ID of the agent that should receive this skill")
    target_agent_name: Optional[str] = Field(default=None, description="Name of target agent (fallback if ID unknown)")
    rationale: str = Field(default="", description="Why this agent is the best fit")
    artifact_declarations: dict = Field(default_factory=dict, description="What the skill produces/consumes")
    dependency_changes: Optional[list[dict]] = Field(default=None, description="Optional DAG dependency changes")


class ArchitectureDesign(BaseModel):
    """Design output from architect phase."""
    capability: str = Field(..., description="Capability being designed")

    # API Design
    function_signature: str = Field(..., description="Function signature")
    input_schema: dict = Field(default_factory=dict, description="Input schema")
    output_schema: dict = Field(default_factory=dict, description="Output schema")

    # Dependencies
    pip_requirements: list[str] = Field(default_factory=list)
    system_requirements: list[str] = Field(default_factory=list)

    # Test cases
    test_cases: list[TestCase] = Field(default_factory=list)

    # Error handling strategy
    error_handling: str = Field(default="", description="How errors should be handled")

    # Design rationale
    design_notes: str = Field(default="", description="Explanation of design decisions")

    # Integration plan (from architect)
    integration_plan: Optional[SkillIntegrationPlan] = Field(default=None, description="Where/how to integrate this skill")

    # Metadata
    design_time_ms: int = Field(default=0, ge=0)


class ReviewFinding(BaseModel):
    """A single finding from code review."""
    severity: str = Field(..., description="critical, warning, info")
    category: str = Field(..., description="security, performance, correctness, style")
    line_range: Optional[tuple[int, int]] = Field(default=None, description="Affected lines")
    description: str = Field(..., description="What the issue is")
    suggestion: Optional[str] = Field(default=None, description="How to fix it")


class ReviewResult(BaseModel):
    """Result of code review phase."""
    approved: bool = Field(..., description="Whether code passed review")
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0, description="0-1 quality score")

    # Findings
    findings: list[ReviewFinding] = Field(default_factory=list)
    critical_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)

    # Security check
    security_passed: bool = Field(default=True)
    security_concerns: list[str] = Field(default_factory=list)

    # Suggestions
    improvement_suggestions: list[str] = Field(default_factory=list)
    refactoring_needed: bool = Field(default=False)

    # Metadata
    review_time_ms: int = Field(default=0, ge=0)


class SemanticValidationResult(BaseModel):
    """Result of semantic validation."""
    passed: bool = Field(..., description="Whether validation passed")
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.01)

    # Comparison details
    expected_type: str = Field(default="any")
    actual_type: str = Field(default="unknown")
    type_match: bool = Field(default=False)

    # Structure comparison (for dicts/lists)
    structure_match: bool = Field(default=True)
    missing_keys: list[str] = Field(default_factory=list)
    extra_keys: list[str] = Field(default_factory=list)

    # Value comparison
    value_comparison: str = Field(default="", description="Description of value differences")

    # LLM assessment (if used)
    llm_reasoning: Optional[str] = Field(default=None)

    # Metadata
    validation_time_ms: int = Field(default=0, ge=0)


class SkillBuildResult(BaseModel):
    """Complete result of team-based skill building."""
    success: bool = Field(..., description="Whether skill was built successfully")

    # Artifact info
    skill_id: Optional[str] = Field(default=None)
    skill_name: Optional[str] = Field(default=None)
    bound_to_agent_id: Optional[str] = Field(default=None)

    # Phase results
    research: Optional[ResearchContext] = Field(default=None)
    design: Optional[ArchitectureDesign] = Field(default=None)
    review: Optional[ReviewResult] = Field(default=None)
    semantic_validation: Optional[SemanticValidationResult] = Field(default=None)

    # Integration
    integration_plan: Optional[SkillIntegrationPlan] = Field(default=None)

    # Code
    final_code: Optional[str] = Field(default=None)
    requirements_txt: Optional[str] = Field(default=None)

    # Iterations
    implementation_iterations: int = Field(default=0, ge=0)
    review_iterations: int = Field(default=0, ge=0)

    # Error info (if failed)
    failure_phase: Optional[TeamRole] = Field(default=None, description="Which phase failed")
    failure_reason: Optional[str] = Field(default=None)
    error_type: Optional[ErrorType] = Field(default=None)

    # Timing
    total_time_ms: int = Field(default=0, ge=0)
    phase_times: dict[str, int] = Field(default_factory=dict, description="Time per phase in ms")

    # Learning data
    attempt_id: Optional[str] = Field(default=None, description="SkillBuildAttempt ID for tracking")


class TestSuiteResult(BaseModel):
    """Result of running a skill's test suite in sandbox."""
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="passed / total")
    details: list[dict] = Field(default_factory=list, description="Per-test results")


class ComparisonResult(BaseModel):
    """Result of comparing a skill against its parent."""
    new_score: float = Field(default=0.0, ge=0.0, le=1.0)
    parent_score: float = Field(default=0.0, ge=0.0, le=1.0)
    regression: bool = Field(default=False, description="True if new skill is worse than parent")
    details: str = Field(default="")


class ActivationResult(BaseModel):
    """Result of skill activation validation gate."""
    approved: bool = Field(default=True)
    reason: str = Field(default="")
    test_result: Optional[TestSuiteResult] = Field(default=None)
    comparison: Optional[ComparisonResult] = Field(default=None)


class SkillBindingCreate(BaseModel):
    """Schema for creating a skill binding."""
    skill_id: str = Field(..., description="ID of the skill to bind")
    agent_id: str = Field(..., description="ID of the agent to bind to")
    capability: str = Field(..., description="Capability this binding provides")
    binding_type: str = Field(default="auto", description="auto, manual, provisional")
    priority: int = Field(default=0, description="Binding priority")


class SkillBindingResponse(BaseModel):
    """Schema for skill binding API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    skill_id: str
    agent_id: str
    capability: str
    binding_type: str
    priority: int
    is_active: bool
    created_at: datetime


class FailurePattern(BaseModel):
    """A learned failure pattern for avoiding repeated mistakes."""
    pattern_type: str = Field(..., description="Type of failure pattern")
    capability_category: str = Field(..., description="Category of capability affected")

    # Pattern details
    error_signature: str = Field(..., description="Regex or exact match for error")
    root_cause: str = Field(default="", description="Identified root cause")

    # Remediation
    fix_strategy: str = Field(default="", description="How to fix this type of error")
    packages_to_avoid: list[str] = Field(default_factory=list)
    packages_to_prefer: list[str] = Field(default_factory=list)

    # Stats
    occurrence_count: int = Field(default=1, ge=1)
    last_seen: Optional[datetime] = Field(default=None)
