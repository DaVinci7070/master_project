from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.dependencies.dependencies import get_db_session
from app.api.v1.endpoints.events import format_sse_event
from app.models.sql.evaluation_models import BenchmarkRun, BenchmarkTaskResult
from app.models.schemas.evaluation_schemas import (
    ColdResetRequest,
    ColdResetResponse,
    EvalTaskProgress,
    RunCompareItem,
    RunCompareResponse,
    RunDetailResponse,
    RunSummary,
    SnapshotInfo,
    StartRunRequest,
    StartRunResponse,
    SuiteDetailResponse,
    SuiteInfo,
    SuiteTaskInfo,
    TaskResultResponse,
    WarmRestoreRequest,
    WarmRestoreResponse,
    WarmSaveRequest,
    WarmSaveResponse,
)
from scripts.evaluation.ablation_modes import MODES
from scripts.evaluation.benchmark_runner import evaluate_pass, load_suite, run_task

router = APIRouter(prefix="/evaluation", tags=["evaluation"])
log = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent.parent.parent.parent.parent / "scripts" / "evaluation" / "datasets"
SNAPSHOTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "snapshots"


_run_lock = asyncio.Lock()


@dataclass
class EvalRunState:
    run_id: str
    suite: str
    ablation_mode: str | None
    seed: int
    status: str = "running"
    started_at: str = ""
    completed_at: str | None = None
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_passed: int = 0
    task_progress: list[dict] = field(default_factory=list)
    full_results: dict | None = None
    error: str | None = None

    @property
    def pass_at_1(self) -> float:
        if self.tasks_total == 0:
            return 0.0
        return round(self.tasks_passed / self.tasks_total, 3)

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "suite": self.suite,
            "ablation_mode": self.ablation_mode,
            "status": self.status,
            "tasks_total": self.tasks_total,
            "tasks_completed": self.tasks_completed,
            "tasks_passed": self.tasks_passed,
            "pass_at_1": self.pass_at_1,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


_eval_runs: dict[str, EvalRunState] = {}


@router.get("/suites", response_model=list[SuiteInfo])
async def list_suites():
    """List available YAML evaluation suites."""
    suites = []
    if not DATASETS_DIR.exists():
        return suites
    for path in sorted(DATASETS_DIR.glob("*.yaml")):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            suites.append(SuiteInfo(
                name=path.stem,
                description=data.get("description"),
                task_count=len(data.get("tasks", [])),
            ))
        except Exception:
            continue
    return suites


@router.get("/suites/{name}", response_model=SuiteDetailResponse)
async def get_suite_detail(name: str):
    """Get suite metadata and task list."""
    path = DATASETS_DIR / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(404, f"Suite '{name}' not found")
    with open(path) as f:
        data = yaml.safe_load(f)
    tasks = []
    for t in data.get("tasks", []):
        gt = t.get("ground_truth", {})
        tasks.append(SuiteTaskInfo(
            task_id=t["task_id"],
            level=t.get("level", "L1"),
            description=t.get("description", ""),
            keywords_count=len(gt.get("required_keywords", [])),
            sections_count=len(gt.get("required_sections", [])),
        ))
    return SuiteDetailResponse(
        name=name,
        description=data.get("description"),
        tasks=tasks,
    )


@router.get("/ablation-modes")
async def get_ablation_modes():
    """Return available ablation modes with their feature flags."""
    return MODES


@router.get("/snapshots", response_model=list[SnapshotInfo])
async def list_snapshots():
    """List available warm snapshot files."""
    snapshots = []
    if not SNAPSHOTS_DIR.exists():
        return snapshots
    for path in sorted(SNAPSHOTS_DIR.glob("*.dump")):
        stat = path.stat()
        snapshots.append(SnapshotInfo(
            filename=path.name,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        ))
    return snapshots


_cold_reset_lock = asyncio.Lock()

@router.post("/cold-reset", response_model=ColdResetResponse)
async def cold_reset_endpoint(request: ColdResetRequest):
    """Truncate all tables, clear Qdrant, re-seed agents."""
    if _cold_reset_lock.locked():
        raise HTTPException(status_code=409, detail="Cold reset already in progress")

    from scripts.evaluation.cold_warm_switch import cold_reset

    async with _cold_reset_lock:
        result = await cold_reset(
            skip_seed=request.skip_seed,
            skip_qdrant=request.skip_qdrant,
            dry_run=request.dry_run,
        )
        return ColdResetResponse(
            tables_truncated=result.get("tables_truncated", 0),
            qdrant_cleared=result.get("qdrant_cleared", []),
            agents_seeded=result.get("agents_seeded", 0),
            dry_run=request.dry_run,
        )


@router.post("/warm-snapshot/save", response_model=WarmSaveResponse)
async def warm_save_endpoint(request: WarmSaveRequest):
    """Create a warm snapshot (pg_dump + Qdrant snapshots)."""
    from scripts.evaluation.cold_warm_switch import warm_snapshot_save

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = str(SNAPSHOTS_DIR / request.snapshot_name)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, warm_snapshot_save, output_path)

    return WarmSaveResponse(
        pg_dump=result.get("pg_dump", ""),
        qdrant_snapshots=[
            s.get("snapshot", "") for s in result.get("qdrant_snapshots", [])
        ],
    )


@router.post("/warm-snapshot/restore", response_model=WarmRestoreResponse)
async def warm_restore_endpoint(request: WarmRestoreRequest):
    """Restore from a warm snapshot."""
    from scripts.evaluation.cold_warm_switch import warm_snapshot_restore

    snapshot_path = str(SNAPSHOTS_DIR / request.snapshot_name)
    if not Path(snapshot_path).exists():
        raise HTTPException(404, f"Snapshot '{request.snapshot_name}' not found")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, warm_snapshot_restore, snapshot_path)

    return WarmRestoreResponse(
        restored_from=result["restored_from"],
        returncode=result["returncode"],
    )


@router.post("/runs", response_model=StartRunResponse)
async def start_run(request: StartRunRequest):
    """Start a benchmark run in the background."""
    suite_path = DATASETS_DIR / f"{request.suite}.yaml"
    if not suite_path.exists():
        raise HTTPException(404, f"Suite '{request.suite}' not found")

    if request.ablation_mode and request.ablation_mode not in MODES:
        raise HTTPException(400, f"Unknown ablation mode '{request.ablation_mode}'. Available: {list(MODES.keys())}")

    for run in _eval_runs.values():
        if run.status == "running":
            raise HTTPException(409, f"Run '{run.run_id}' is already in progress. Wait for it to complete.")

    run_id = str(uuid4())
    suite_data = load_suite(request.suite)
    tasks = suite_data.get("tasks", [])

    run_state = EvalRunState(
        run_id=run_id,
        suite=request.suite,
        ablation_mode=request.ablation_mode,
        seed=request.seed,
        started_at=datetime.now(timezone.utc).isoformat(),
        tasks_total=len(tasks),
        task_progress=[
            {"task_id": t["task_id"], "level": t.get("level", "L1"), "status": "pending",
             "duration_ms": 0, "pass_result": None, "score": 0.0, "error": None}
            for t in tasks
        ],
    )
    _eval_runs[run_id] = run_state

    asyncio.create_task(_run_benchmark(run_state, tasks, request))

    return StartRunResponse(run_id=run_id, status="running")


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(session: AsyncSession = Depends(get_db_session)):
    """List all evaluation runs (persistent from DB + in-memory active)."""
    result = await session.execute(
        select(BenchmarkRun).order_by(BenchmarkRun.started_at.desc())
    )
    db_runs = result.scalars().all()

    summaries = []
    db_run_ids = set()
    for r in db_runs:
        db_run_ids.add(r.id)
        summaries.append(RunSummary(
            run_id=r.id,
            suite=r.suite,
            ablation_mode=r.ablation_mode,
            status=r.status,
            tasks_total=r.tasks_total,
            tasks_completed=r.tasks_passed + (r.tasks_total - r.tasks_passed) if r.status == "completed" else r.tasks_passed,
            tasks_passed=r.tasks_passed,
            pass_at_1=r.pass_at_1,
            started_at=r.started_at.isoformat() if r.started_at else "",
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
        ))

    for run in _eval_runs.values():
        if run.run_id not in db_run_ids:
            summaries.append(RunSummary(**run.summary()))

    return summaries


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(run_id: str, session: AsyncSession = Depends(get_db_session)):
    """Get detailed results for a specific run (from DB)."""
    result = await session.execute(
        select(BenchmarkRun).where(BenchmarkRun.id == run_id)
    )
    db_run = result.scalar_one_or_none()

    if db_run:
        tr_result = await session.execute(
            select(BenchmarkTaskResult)
            .where(BenchmarkTaskResult.run_id == run_id)
            .order_by(BenchmarkTaskResult.task_id)
        )
        task_results = tr_result.scalars().all()

        return RunDetailResponse(
            run_id=db_run.id,
            suite=db_run.suite,
            ablation_mode=db_run.ablation_mode,
            seed=db_run.seed,
            status=db_run.status,
            started_at=db_run.started_at.isoformat() if db_run.started_at else "",
            completed_at=db_run.completed_at.isoformat() if db_run.completed_at else None,
            tasks_total=db_run.tasks_total,
            tasks_passed=db_run.tasks_passed,
            pass_at_1=db_run.pass_at_1,
            total_tokens=db_run.total_tokens,
            total_tokens_input=db_run.total_tokens_input,
            total_tokens_output=db_run.total_tokens_output,
            total_duration_ms=db_run.total_duration_ms,
            avg_score=db_run.avg_score,
            task_results=[
                TaskResultResponse(
                    task_id=tr.task_id,
                    level=tr.level,
                    status=tr.status,
                    pass_result=tr.passed,
                    score=tr.score,
                    duration_ms=tr.duration_ms,
                    agents_executed=tr.agents_executed,
                    tokens_total=tr.tokens_total,
                    tokens_input=tr.tokens_input,
                    tokens_output=tr.tokens_output,
                    missing_keywords=tr.missing_keywords or [],
                    missing_sections=tr.missing_sections or [],
                    error=tr.error,
                    challenge_id=tr.challenge_id,
                )
                for tr in task_results
            ],
        )

    run = _eval_runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found")

    return RunDetailResponse(
        run_id=run.run_id,
        suite=run.suite,
        ablation_mode=run.ablation_mode,
        seed=run.seed,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        tasks_total=run.tasks_total,
        tasks_passed=run.tasks_passed,
        pass_at_1=run.pass_at_1,
        total_tokens=0,
        total_tokens_input=0,
        total_tokens_output=0,
        total_duration_ms=0,
        avg_score=0.0,
        task_results=[
            TaskResultResponse(
                task_id=tp["task_id"],
                level=tp.get("level"),
                status=tp["status"],
                pass_result=tp.get("pass_result"),
                score=tp.get("score", 0.0),
                duration_ms=tp.get("duration_ms", 0),
                missing_keywords=tp.get("missing_keywords", []),
                missing_sections=tp.get("missing_sections", []),
                error=tp.get("error"),
            )
            for tp in run.task_progress
        ],
    )


@router.get("/compare", response_model=RunCompareResponse)
async def compare_runs(
    run_ids: str = Query(..., description="Comma-separated run IDs"),
    session: AsyncSession = Depends(get_db_session),
):
    """Compare metrics across multiple benchmark runs."""
    ids = [rid.strip() for rid in run_ids.split(",") if rid.strip()]
    if len(ids) < 2:
        raise HTTPException(400, "Provide at least 2 run_ids to compare")

    result = await session.execute(
        select(BenchmarkRun).where(BenchmarkRun.id.in_(ids))
    )
    runs = result.scalars().all()

    if len(runs) < 2:
        raise HTTPException(404, "Not enough runs found in DB for comparison")

    items = [
        RunCompareItem(
            run_id=r.id,
            suite=r.suite,
            ablation_mode=r.ablation_mode,
            status=r.status,
            pass_at_1=r.pass_at_1,
            avg_score=r.avg_score,
            total_tokens=r.total_tokens,
            total_tokens_input=r.total_tokens_input,
            total_tokens_output=r.total_tokens_output,
            total_duration_ms=r.total_duration_ms,
            tasks_total=r.tasks_total,
            tasks_passed=r.tasks_passed,
            started_at=r.started_at.isoformat() if r.started_at else "",
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
        )
        for r in sorted(runs, key=lambda x: x.started_at)
    ]

    first, last = items[0], items[-1]
    delta = {
        "pass_at_1": round(last.pass_at_1 - first.pass_at_1, 3),
        "avg_score": round(last.avg_score - first.avg_score, 3),
        "total_tokens": last.total_tokens - first.total_tokens,
        "total_duration_ms": last.total_duration_ms - first.total_duration_ms,
        "tasks_passed": last.tasks_passed - first.tasks_passed,
    }

    return RunCompareResponse(runs=items, delta=delta)


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """SSE stream for live benchmark run progress."""
    if run_id not in _eval_runs:
        raise HTTPException(404, f"Run '{run_id}' not found")

    return StreamingResponse(
        _eval_stream_generator(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _eval_stream_generator(run_id: str) -> AsyncGenerator[str, None]:
    last_seen = 0
    heartbeat_counter = 0

    while True:
        run = _eval_runs.get(run_id)
        if not run:
            yield format_sse_event("error", {"message": "Run not found"})
            return

        for i, tp in enumerate(run.task_progress[last_seen:], start=last_seen):
            if tp["status"] not in ("pending", "running"):
                yield format_sse_event("task_complete", {
                    "index": i,
                    **tp,
                    "tasks_completed": run.tasks_completed,
                    "tasks_total": run.tasks_total,
                    "pass_at_1": run.pass_at_1,
                })
                last_seen = i + 1

        if run.status in ("completed", "failed"):
            yield format_sse_event("run_complete", {
                **run.summary(),
                "error": run.error,
            })
            return

        heartbeat_counter += 1
        if heartbeat_counter % 10 == 0:
            yield format_sse_event("heartbeat", {"ts": datetime.now(timezone.utc).isoformat()})

        await asyncio.sleep(1.0)


async def _run_benchmark(
    run_state: EvalRunState,
    tasks: list[dict],
    request: StartRunRequest,
) -> None:
    """Execute benchmark tasks sequentially, updating run_state in-place and persisting to DB."""
    from app.dependencies.dependencies import AsyncSessionLocal

    original_flags: dict | None = None
    if request.ablation_mode:
        mode_flags = MODES[request.ablation_mode]
        original_flags = {
            "autonomous_evolution_enabled": settings.autonomous_evolution_enabled,
            "shared_memory_enabled": settings.shared_memory_enabled,
            "skill_reuse_enabled": settings.skill_reuse_enabled,
        }
        settings.autonomous_evolution_enabled = mode_flags["AUTONOMOUS_EVOLUTION_ENABLED"] == "true"
        settings.shared_memory_enabled = mode_flags["SHARED_MEMORY_ENABLED"] == "true"
        settings.skill_reuse_enabled = mode_flags["SKILL_REUSE_ENABLED"] == "true"
        log.info("Ablation mode '%s' applied: %s", request.ablation_mode, mode_flags)

    base_url = "http://localhost:8000/api/v1"
    task_db_results: list[BenchmarkTaskResult] = []

    async with AsyncSessionLocal() as db:
        db_run = BenchmarkRun(
            id=run_state.run_id,
            suite=run_state.suite,
            ablation_mode=run_state.ablation_mode,
            seed=run_state.seed,
            status="running",
            started_at=datetime.fromisoformat(run_state.started_at),
            tasks_total=run_state.tasks_total,
        )
        db.add(db_run)
        await db.commit()

    from app.core.llm_client import LLMClient
    llm_client = LLMClient()

    try:
        async with httpx.AsyncClient() as client:
            for idx, task in enumerate(tasks):
                run_state.task_progress[idx]["status"] = "running"

                t0 = time.monotonic()
                result = await run_task(
                    client=client,
                    base_url=base_url,
                    task=task,
                    project_id=request.project_id,
                    timeout=request.timeout,
                    poll_interval=request.poll_interval,
                    llm_client=llm_client,
                )
                elapsed_ms = int((time.monotonic() - t0) * 1000)

                passed = result.get("pass", False)
                status = "passed" if passed else result.get("status", "failed")

                run_state.task_progress[idx].update({
                    "status": status,
                    "duration_ms": elapsed_ms,
                    "pass_result": passed,
                    "score": result.get("score", 0.0),
                    "error": result.get("error"),
                    "missing_keywords": result.get("missing_keywords", []),
                    "missing_sections": result.get("missing_sections", []),
                })
                run_state.tasks_completed += 1
                if passed:
                    run_state.tasks_passed += 1

                task_db_results.append(BenchmarkTaskResult(
                    id=str(uuid4()),
                    run_id=run_state.run_id,
                    task_id=task["task_id"],
                    level=task.get("level"),
                    status=status,
                    passed=passed,
                    score=result.get("score", 0.0),
                    duration_ms=elapsed_ms,
                    agents_executed=result.get("agents_executed", 0),
                    tokens_total=result.get("tokens_total", 0),
                    tokens_input=result.get("tokens_input", 0),
                    tokens_output=result.get("tokens_output", 0),
                    missing_keywords=result.get("missing_keywords", []),
                    missing_sections=result.get("missing_sections", []),
                    error=result.get("error"),
                    challenge_id=result.get("challenge_id"),
                ))

                log.info(
                    "Task %s: %s (%dms, %d tokens)",
                    task["task_id"], status, elapsed_ms, result.get("tokens_total", 0),
                )

        run_state.status = "completed"
        run_state.completed_at = datetime.now(timezone.utc).isoformat()
        log.info(
            "Run %s completed: %d/%d passed (Pass@1=%.1f%%)",
            run_state.run_id, run_state.tasks_passed,
            run_state.tasks_total, run_state.pass_at_1 * 100,
        )

    except Exception as e:
        run_state.status = "failed"
        run_state.error = str(e)
        run_state.completed_at = datetime.now(timezone.utc).isoformat()
        log.error("Run %s failed: %s", run_state.run_id, e)

    finally:
        if original_flags:
            settings.autonomous_evolution_enabled = original_flags["autonomous_evolution_enabled"]
            settings.shared_memory_enabled = original_flags["shared_memory_enabled"]
            settings.skill_reuse_enabled = original_flags["skill_reuse_enabled"]
            log.info("Ablation mode restored to original settings")

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(BenchmarkRun).where(BenchmarkRun.id == run_state.run_id)
                )
                db_run = result.scalar_one_or_none()
                if db_run:
                    db_run.status = run_state.status
                    db_run.completed_at = datetime.now(timezone.utc)
                    db_run.tasks_passed = run_state.tasks_passed
                    db_run.pass_at_1 = run_state.pass_at_1

                    total_tokens = sum(tr.tokens_total for tr in task_db_results)
                    total_input = sum(tr.tokens_input for tr in task_db_results)
                    total_output = sum(tr.tokens_output for tr in task_db_results)
                    total_duration = sum(tr.duration_ms for tr in task_db_results)
                    scores = [tr.score for tr in task_db_results if tr.score > 0]
                    avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0

                    db_run.total_tokens = total_tokens
                    db_run.total_tokens_input = total_input
                    db_run.total_tokens_output = total_output
                    db_run.total_duration_ms = total_duration
                    db_run.avg_score = avg_score

                    for tr in task_db_results:
                        db.add(tr)

                    await db.commit()
                    log.info("Run %s persisted to DB (%d task results)", run_state.run_id, len(task_db_results))
        except Exception as e:
            log.error("Failed to persist run %s to DB: %s", run_state.run_id, e)
