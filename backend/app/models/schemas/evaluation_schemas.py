from __future__ import annotations

from pydantic import BaseModel, Field


class ColdResetRequest(BaseModel):
    skip_seed: bool = False
    skip_qdrant: bool = False
    dry_run: bool = False


class ColdResetResponse(BaseModel):
    tables_truncated: int
    qdrant_cleared: list[str]
    agents_seeded: int
    dry_run: bool


class WarmSaveRequest(BaseModel):
    snapshot_name: str = Field(..., min_length=1, description="Filename without path")


class WarmSaveResponse(BaseModel):
    pg_dump: str
    qdrant_snapshots: list[str]


class WarmRestoreRequest(BaseModel):
    snapshot_name: str = Field(..., min_length=1)


class WarmRestoreResponse(BaseModel):
    restored_from: str
    returncode: int


class SnapshotInfo(BaseModel):
    filename: str
    size_bytes: int
    modified_at: str


class SuiteInfo(BaseModel):
    name: str
    description: str | None = None
    task_count: int


class SuiteTaskInfo(BaseModel):
    task_id: str
    level: str
    description: str
    keywords_count: int
    sections_count: int


class SuiteDetailResponse(BaseModel):
    name: str
    description: str | None = None
    tasks: list[SuiteTaskInfo]


class StartRunRequest(BaseModel):
    suite: str
    ablation_mode: str | None = None
    seed: int = 1
    timeout: int = 600
    poll_interval: int = 5
    project_id: str = "evaluation"


class StartRunResponse(BaseModel):
    run_id: str
    status: str


class EvalTaskProgress(BaseModel):
    task_id: str
    level: str
    status: str = "pending"
    duration_ms: int = 0
    pass_result: bool | None = None
    score: float = 0.0
    error: str | None = None
    missing_keywords: list[str] = []
    missing_sections: list[str] = []


class RunStatusResponse(BaseModel):
    run_id: str
    suite: str
    ablation_mode: str | None
    seed: int
    status: str
    tasks_total: int
    tasks_completed: int
    tasks_passed: int
    pass_at_1: float
    task_progress: list[EvalTaskProgress]
    started_at: str
    completed_at: str | None = None
    error: str | None = None


class RunSummary(BaseModel):
    run_id: str
    suite: str
    ablation_mode: str | None
    status: str
    tasks_total: int
    tasks_completed: int
    tasks_passed: int
    pass_at_1: float
    started_at: str
    completed_at: str | None = None


class TaskResultResponse(BaseModel):
    task_id: str
    level: str | None = None
    status: str | None = None
    pass_result: bool | None = None
    score: float = 0.0
    duration_ms: int = 0
    agents_executed: int = 0
    tokens_total: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    missing_keywords: list[str] = []
    missing_sections: list[str] = []
    error: str | None = None
    challenge_id: str | None = None


class RunDetailResponse(BaseModel):
    run_id: str
    suite: str
    ablation_mode: str | None = None
    seed: int | None = None
    status: str
    started_at: str
    completed_at: str | None = None
    tasks_total: int = 0
    tasks_passed: int = 0
    pass_at_1: float = 0.0
    total_tokens: int = 0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_duration_ms: int = 0
    avg_score: float = 0.0
    task_results: list[TaskResultResponse] = []


class RunCompareItem(BaseModel):
    run_id: str
    suite: str
    ablation_mode: str | None = None
    status: str
    pass_at_1: float = 0.0
    avg_score: float = 0.0
    total_tokens: int = 0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_duration_ms: int = 0
    tasks_total: int = 0
    tasks_passed: int = 0
    started_at: str
    completed_at: str | None = None


class RunCompareResponse(BaseModel):
    runs: list[RunCompareItem]
    delta: dict = {}
