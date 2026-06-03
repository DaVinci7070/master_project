from urllib.parse import urlparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://lumari:lumari_dev@localhost:5432/lumari"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "reports"
    qdrant_prefer_grpc: bool = False

    embed_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    llm_model: str = "gemini/gemini-3-flash-preview"
    llm_api_base: str | None = None
    llm_timeout: float = 120.0

    orchestrator_url: str = "http://10.244.84.3:8000"
    gpu_url: str = "http://10.244.84.3:8010"
    redis_url: str = "redis://localhost:6379"

    api_secret: str = "lumari-demo-2026"
    default_user_id: str = "demo-user-001"
    environment: str = "development"
    log_level: str = "INFO"

    rate_limit_per_minute: int = 120
    rate_limit_suspicious_threshold: int = 3
    ip_block_duration_hours: int = 24

    control_agent_temperature: float = 0.2
    control_agent_max_batch: int = 3
    control_agent_history_days: int = 7
    control_agent_max_strikes: int = 3
    control_agent_pattern_threshold: int = 3

    skill_researcher_model: str | None = None
    skill_architect_model: str | None = "gemini/gemini-3-flash-preview"
    skill_implementer_model: str | None = "gemini/gemini-3-flash-preview"
    skill_reviewer_model: str | None = "gemini/gemini-3-flash-preview"

    semantic_validation_enabled: bool = True
    semantic_similarity_threshold: float = 0.7

    code_alignment_enabled: bool = True
    code_alignment_threshold: float = 0.7
    code_alignment_model: str | None = None

    research_cache_ttl_hours: int = 24
    web_search_enabled: bool = True

    failure_history_max_items: int = 5
    failure_history_days: int = 30

    skill_directory_enabled: bool = True
    skill_directory_path: str = "skills"

    hot_reload_enabled: bool = True

    intra_execution_self_healing_enabled: bool = True
    self_healing_build_timeout: int = 600
    self_healing_max_builds_per_execution: int = 3

    build_total_timeout: int = 900

    execution_hard_timeout: int = 1200
    agent_execution_timeout: int = 300

    autonomous_evolution_enabled: bool = True

    shared_memory_enabled: bool = True
    skill_reuse_enabled: bool = True

    shared_memory_max_items: int = 8
    shared_memory_max_tokens: int = 4000
    shared_memory_top_k: int = 5
    shared_memory_score_threshold: float = 0.30

    verify_adapt_enabled: bool = True
    max_adapt_rounds: int = 3
    verification_completeness_threshold: float = 0.85
    adapt_threshold_new_team: float = 0.4
    adapt_threshold_escalate: float = 0.1

    team_assembly_enabled: bool = True
    team_assembly_timeout: int = 30
    team_assembly_fallback_to_default: bool = True

    agent_promotion_enabled: bool = True
    agent_promotion_min_score: float = 0.7
    strategy_memory_enabled: bool = True

    cot_verification_enabled: bool = True
    self_reflection_enabled: bool = True
    self_reflection_margin: float = 0.1

    failure_reflection_enabled: bool = True

    execution_reflection_enabled: bool = True
    reflection_memory_max_items: int = 3

    sandbox_postgres_host: str = "lumari-postgres"
    sandbox_postgres_port: int = 5432
    sandbox_qdrant_host: str = "lumari-qdrant"
    sandbox_qdrant_port: int = 6333

    class Config:
        env_file = ".env"
        extra = "ignore"

    def _parse_db_credentials(self) -> dict[str, str]:
        """Extrahiert User/Password/DB aus database_url."""
        clean_url = self.database_url.replace("+asyncpg", "")
        parsed = urlparse(clean_url)
        return {
            "user": parsed.username or "lumari",
            "password": parsed.password or "lumari_dev",
            "dbname": (parsed.path or "/lumari").lstrip("/"),
        }

    def get_sandbox_env_vars(self) -> dict[str, str]:
        """Env-Vars für Sandbox-Container mit echten Service-Adressen."""
        creds = self._parse_db_credentials()
        pg_url = (
            f"postgresql://{creds['user']}:{creds['password']}"
            f"@{self.sandbox_postgres_host}:{self.sandbox_postgres_port}"
            f"/{creds['dbname']}"
        )
        return {
            "DATABASE_URL": pg_url,
            "POSTGRES_HOST": self.sandbox_postgres_host,
            "POSTGRES_PORT": str(self.sandbox_postgres_port),
            "POSTGRES_USER": creds["user"],
            "POSTGRES_PASSWORD": creds["password"],
            "POSTGRES_DB": creds["dbname"],
            "QDRANT_URL": f"http://{self.sandbox_qdrant_host}:{self.sandbox_qdrant_port}",
            "QDRANT_HOST": self.sandbox_qdrant_host,
            "QDRANT_PORT": str(self.sandbox_qdrant_port),
        }

    def get_sandbox_infrastructure_context(self) -> str:
        """Infrastruktur-Beschreibung fuer Architect/Implementer-Prompts."""
        env = self.get_sandbox_env_vars()
        return f"""## Sandbox Infrastructure
The code runs in a Docker container (python:3.11-slim) on the 'lumari-network'.
The container HAS full network access — pip install and apt-get work at runtime.

### Base Image & Packages
- Image: python:3.11-slim (Debian bookworm)
- Pre-installed: Python 3.11 stdlib ONLY (no third-party packages)
- pip and apt-get are available (runs as root)

### Correct PyPI Package Names (use EXACTLY these):
- PostgreSQL driver: psycopg2-binary (NOT 'postgresql', NOT bare 'psycopg2')
- OpenCV: opencv-python (NOT 'opencv', NOT 'cv2')
- PDF reading: pypdf or pdfplumber (NOT 'PyPDF2')
- HTTP client: httpx or requests
- Audio: faster-whisper + apt package ffmpeg

### Reachable Network Hosts:
- lumari-postgres:5432 — Lumari Hauptdatenbank
- lumari-qdrant:6333 — Qdrant Vector-DB
- benchmark-db:5432 — Benchmark-Datenbank (separate DB fuer Evaluationsaufgaben)
- IMPORTANT: 'host.docker.internal' is NOT available in this network mode
- If a task references an unreachable host, use the closest matching host from this list

### Connection Best Practices:
- Always use connect_timeout=10 for database connections
- Implement retry (3 attempts, exponential backoff) for all external connections
- DNS resolution inside Docker can take 1-2s on first access — retries prevent transient failures
- After writing data to a database, always verify with a SELECT COUNT(*) before returning

### File Mounts:
- /data/ — read-only bind mount of the uploads directory (input files)
- /workspace/ — writable working directory for temporary files

### Services for TEST CASES ONLY:
- PostgreSQL: {env['DATABASE_URL']}
- Qdrant: {env['QDRANT_URL']}

### Rules for TEST CASES:
- Use the connection strings above for test_cases input data
- For PostgreSQL test_cases, use input like: {{"database_url": "{env['DATABASE_URL']}"}}
- For Qdrant test_cases, use input like: {{"qdrant_url": "{env['QDRANT_URL']}"}}
- Database tests MUST be READ-ONLY: only SELECT, never INSERT/UPDATE/DELETE/DROP/CREATE

### Rules for IMPLEMENTATION CODE (execute function):
- All connection URLs, hosts, ports, credentials MUST come from input_data parameters
- NEVER read os.environ — the caller passes everything via input_data
- NEVER validate or restrict which hosts/databases the skill connects to
- NEVER add hostname whitelists, port checks, or allowed-hosts lists
- The skill is a generic tool — it connects wherever input_data tells it to"""


settings = Settings()
