from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://lumari:lumari_dev@localhost:5432/lumari"

    # Qdrant Vector Database
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "reports"
    qdrant_prefer_grpc: bool = False

    # Embedding Model
    embed_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # LLM Configuration (LiteLLM)
    # Provider examples:
    #   - Gemini: "gemini/gemini-2.0-flash"
    #   - OpenAI: "gpt-4o"
    #   - Anthropic: "claude-3-5-sonnet-20241022"
    #   - vLLM: "hosted_vllm/model-name" (set llm_api_base)
    #   - Ollama: "ollama/llama3.2" (set llm_api_base)
    llm_model: str = "gemini/gemini-3.1-flash-lite-preview"
    llm_api_base: str | None = None
    llm_timeout: float = 120.0

    # Legacy service URLs (may be deprecated)
    orchestrator_url: str = "http://10.244.84.3:8000"
    gpu_url: str = "http://10.244.84.3:8010"
    redis_url: str = "redis://localhost:6379"

    # API Settings
    api_secret: str = "lumari-demo-2026"
    default_user_id: str = "demo-user-001"
    environment: str = "development"
    log_level: str = "INFO"

    # Rate Limiting & Security
    rate_limit_per_minute: int = 120
    rate_limit_suspicious_threshold: int = 3
    ip_block_duration_hours: int = 24

    # Control Agent settings
    control_agent_temperature: float = 0.2  # Deterministic decisions
    control_agent_max_batch: int = 3  # Max improvements per cycle
    control_agent_history_days: int = 7  # Days of finding history for context
    control_agent_max_strikes: int = 3  # 3-strike rule limit
    control_agent_pattern_threshold: int = 3  # Times info-level must repeat to escalate

    # Skill Team settings
    skill_team_enabled: bool = True  # Enable team-based skill development
    skill_researcher_model: str | None = None  # Model for research (default: fast)
    skill_architect_model: str | None = "claude-3-5-sonnet-20241022"  # Model for design
    skill_implementer_model: str | None = "gemini/gemini-3-flash-preview"  # Strong model for code generation
    skill_reviewer_model: str | None = "claude-3-5-sonnet-20241022"  # Model for review

    # Semantic Validation settings
    semantic_validation_enabled: bool = True  # Enable semantic output validation
    semantic_similarity_threshold: float = 0.7  # Minimum similarity score

    # Research settings
    research_cache_ttl_hours: int = 24  # How long to cache research results
    web_search_enabled: bool = True  # Enable web search in research phase

    # Self-Improving Loop settings (OpenClaw-style)
    failure_history_max_items: int = 5  # Max failures to include in prompts
    failure_history_days: int = 30  # How far back to look for failures

    # Skill Directory settings (for SKILL.md format - Phase 2)
    skill_directory_enabled: bool = True  # Enable SKILL.md directory format
    skill_directory_path: str = "skills"  # Where to store skill directories (relative to backend/)

    # Hot-Reload settings (Phase 3)
    hot_reload_enabled: bool = True  # Enable in-memory skill registry

    # Self-Healing settings (Sprint 4)
    intra_execution_self_healing_enabled: bool = True  # Enable self-healing during execution (on_unknown_tool -> build skill)
    self_healing_build_timeout: int = 180  # Max seconds for on-demand skill build
    self_healing_max_builds_per_execution: int = 3  # Max on-demand skill builds per execution

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
