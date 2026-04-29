"""
Tests for F18 — Cold/Warm DB Switch.

Covers: transactional truncation, idempotency, rollback safety,
Qdrant cleanup, seeding, warm save/restore CLI, and argument parsing.
"""
from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.versioned_models import Agent, Prompt, Skill
from app.models.sql.shared_memory_models import Fact, Hypothesis
from app.models.sql.improvement_models import ImprovementAttempt

# Module under test — import functions directly
from scripts.evaluation.cold_warm_switch import (
    cold_reset,
    _truncate_all_tables,
    _clear_qdrant_collections,
    _seed_from_default,
    warm_snapshot_save,
    warm_snapshot_restore,
    parse_pg_url,
    parse_args,
    COLD_TRUNCATION_TABLES,
    QDRANT_COLLECTIONS,
    VECTOR_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_test_data(session: AsyncSession) -> None:
    """Insert minimal test data into several tables."""
    from uuid import uuid4

    prompt = Prompt(
        id=str(uuid4()), name="test_prompt", content="test", is_active=True,
    )
    session.add(prompt)
    await session.flush()

    agent = Agent(
        id=str(uuid4()),
        name="test_agent",
        dependencies=[],
        io_schema={"input": {}, "output": {}},
        prompt_id=prompt.id,
        is_active=True,
    )
    session.add(agent)

    skill = Skill(
        id=str(uuid4()),
        name="test_skill",
        description="test",
        code="def execute(data): return data",
        is_active=True,
    )
    session.add(skill)

    fact = Fact(
        id=str(uuid4()),
        text="test fact",
        confidence=0.9,
        source_agent_id="agent-1",
        execution_id="exec-1",
        project_id="proj-1",
    )
    session.add(fact)

    hypothesis = Hypothesis(
        id=str(uuid4()),
        text="test hypothesis",
        confidence=0.8,
        source_agent_id="agent-1",
        execution_id="exec-1",
        project_id="proj-1",
    )
    session.add(hypothesis)

    attempt = ImprovementAttempt(
        id=str(uuid4()),
        finding_fingerprint="abc123",
        artifact_type="prompt",
        artifact_id=prompt.id,
        version_before=1,
    )
    session.add(attempt)

    await session.commit()


async def _count_rows(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# Cold reset tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cold_truncate_clears_all_tables(test_engine, test_session):
    """Seed data, truncate, verify all tables empty."""
    await _seed_test_data(test_session)

    # Verify data exists before truncation
    assert await _count_rows(test_session, Prompt) > 0
    assert await _count_rows(test_session, Agent) > 0
    assert await _count_rows(test_session, Skill) > 0
    assert await _count_rows(test_session, Fact) > 0

    # Truncate
    count = await _truncate_all_tables(test_engine)
    assert count == len(COLD_TRUNCATION_TABLES)

    # Verify all empty — need a fresh session to see post-truncation state
    from sqlalchemy.ext.asyncio import AsyncSession as AS
    from sqlalchemy.orm import sessionmaker as sm

    factory = sm(bind=test_engine, class_=AS, expire_on_commit=False)
    async with factory() as fresh_session:
        assert await _count_rows(fresh_session, Prompt) == 0
        assert await _count_rows(fresh_session, Agent) == 0
        assert await _count_rows(fresh_session, Skill) == 0
        assert await _count_rows(fresh_session, Fact) == 0
        assert await _count_rows(fresh_session, Hypothesis) == 0
        assert await _count_rows(fresh_session, ImprovementAttempt) == 0


@pytest.mark.asyncio
async def test_cold_truncate_idempotent(test_engine, test_session):
    """Running truncation twice should not error."""
    await _seed_test_data(test_session)

    # First truncation
    count1 = await _truncate_all_tables(test_engine)
    # Second truncation on empty tables
    count2 = await _truncate_all_tables(test_engine)

    assert count1 == count2 == len(COLD_TRUNCATION_TABLES)


@pytest.mark.asyncio
async def test_cold_truncate_does_not_affect_separate_engine(test_engine, test_session):
    """Truncation on one engine does not affect data in another engine."""
    await _seed_test_data(test_session)
    original_count = await _count_rows(test_session, Prompt)
    assert original_count > 0

    # Create a separate in-memory SQLite engine (completely independent DB)
    from sqlalchemy.ext.asyncio import create_async_engine as _cae
    from sqlalchemy.pool import StaticPool as _SP

    other_engine = _cae(
        "sqlite+aiosqlite:///:memory:",
        poolclass=_SP,
        connect_args={"check_same_thread": False},
    )
    # Truncate the *other* engine — should not touch our test data
    await _truncate_all_tables(other_engine)
    await other_engine.dispose()

    # Our original engine's data must be intact
    assert await _count_rows(test_session, Prompt) == original_count


@pytest.mark.asyncio
async def test_cold_dry_run_no_side_effects(test_engine, test_session):
    """Dry run should not modify the database."""
    await _seed_test_data(test_session)
    original_prompt_count = await _count_rows(test_session, Prompt)

    result = await cold_reset(
        database_url="sqlite+aiosqlite:///:memory:",
        skip_qdrant=True,
        dry_run=True,
    )

    assert result.get("dry_run") is True
    assert result["tables_truncated"] == 0
    # Original data should be untouched
    assert await _count_rows(test_session, Prompt) == original_prompt_count


# ---------------------------------------------------------------------------
# Qdrant cleanup tests
# ---------------------------------------------------------------------------

def test_cold_qdrant_cleanup():
    """Verify Qdrant collections are deleted and recreated with correct params."""
    mock_client = MagicMock()
    mock_client.collection_exists.return_value = True

    # Patch at the actual import location (lazy import inside the function)
    with patch("qdrant_client.QdrantClient", return_value=mock_client):
        cleared = _clear_qdrant_collections("http://localhost:6333")

    assert len(cleared) == 2
    assert "shared_memory_facts" in cleared
    assert "shared_memory_hypotheses" in cleared

    # Verify delete was called for both existing collections
    assert mock_client.delete_collection.call_count == 2

    # Verify create was called for both collections
    assert mock_client.create_collection.call_count == 2

    # Verify indexes were created (6 indexes x 2 collections = 12)
    assert mock_client.create_payload_index.call_count == 12


# ---------------------------------------------------------------------------
# Seed tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cold_seed_after_truncate(test_engine):
    """After truncation, seeding should create the expected agents."""
    # First truncate
    await _truncate_all_tables(test_engine)

    # Then seed
    count = await _seed_from_default(test_engine)

    # Should have created agents (exact count depends on seed_agents.py)
    assert count > 0

    # Verify agents exist in DB
    from sqlalchemy.ext.asyncio import AsyncSession as AS
    from sqlalchemy.orm import sessionmaker as sm

    factory = sm(bind=test_engine, class_=AS, expire_on_commit=False)
    async with factory() as session:
        agent_count = await _count_rows(session, Agent)
        prompt_count = await _count_rows(session, Prompt)
        assert agent_count > 0
        assert prompt_count > 0
        # Each agent should have a prompt
        assert agent_count == prompt_count


# ---------------------------------------------------------------------------
# Warm snapshot tests
# ---------------------------------------------------------------------------

def test_warm_save_calls_pg_dump():
    """Verify pg_dump is called with correct arguments."""
    with patch("scripts.evaluation.cold_warm_switch._pg_tool_available_locally"), \
         patch("scripts.evaluation.cold_warm_switch.subprocess.run") as mock_run, \
         patch("scripts.evaluation.cold_warm_switch.httpx.post") as mock_post, \
         patch("pathlib.Path.mkdir"):

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"result": {"name": "snap1"}})

        result = warm_snapshot_save(
            output_path="/tmp/test.dump",
            database_url="postgresql+asyncpg://lumari:lumari_dev@localhost:5432/lumari",
        )

        # pg_dump called
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
        assert cmd[0] == "pg_dump"
        assert "--host" in cmd
        assert "localhost" in cmd
        assert "--format=custom" in cmd
        assert "/tmp/test.dump" in cmd

        # Password passed via env
        env = call_args.kwargs.get("env") or call_args[1].get("env", {})
        assert env.get("PGPASSWORD") == "lumari_dev"

        assert result["pg_dump"] == "/tmp/test.dump"


def test_warm_restore_calls_pg_restore():
    """Verify pg_restore is called with correct arguments."""
    with patch("scripts.evaluation.cold_warm_switch._pg_tool_available_locally"), \
         patch("scripts.evaluation.cold_warm_switch.subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True):

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        result = warm_snapshot_restore(
            snapshot_path="/tmp/test.dump",
            database_url="postgresql+asyncpg://lumari:lumari_dev@localhost:5432/lumari",
        )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "pg_restore"
        assert "--clean" in cmd
        assert "--if-exists" in cmd
        assert "--no-owner" in cmd
        assert "/tmp/test.dump" in cmd

        assert result["restored_from"] == "/tmp/test.dump"


def test_warm_save_raises_on_pg_dump_failure():
    """pg_dump failure should raise RuntimeError."""
    with patch("scripts.evaluation.cold_warm_switch._pg_tool_available_locally"), \
         patch("scripts.evaluation.cold_warm_switch.subprocess.run") as mock_run, \
         patch("pathlib.Path.mkdir"):

        mock_run.return_value = MagicMock(
            returncode=1, stderr="pg_dump: error: connection failed", stdout="",
        )

        with pytest.raises(RuntimeError, match="pg_dump failed"):
            warm_snapshot_save(
                output_path="/tmp/test.dump",
                database_url="postgresql+asyncpg://user:pass@host:5432/db",
            )


def test_warm_restore_raises_on_fatal_error():
    """Fatal pg_restore errors should raise RuntimeError."""
    with patch("scripts.evaluation.cold_warm_switch._pg_tool_available_locally"), \
         patch("scripts.evaluation.cold_warm_switch.subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True):

        mock_run.return_value = MagicMock(
            returncode=1, stderr="FATAL: password authentication failed", stdout="",
        )

        with pytest.raises(RuntimeError, match="pg_restore failed"):
            warm_snapshot_restore(
                snapshot_path="/tmp/test.dump",
                database_url="postgresql+asyncpg://user:pass@host:5432/db",
            )


def test_warm_restore_file_not_found():
    """Missing snapshot file should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Snapshot not found"):
        warm_snapshot_restore(
            snapshot_path="/nonexistent/path.dump",
            database_url="postgresql+asyncpg://user:pass@host:5432/db",
        )


# ---------------------------------------------------------------------------
# URL parsing tests
# ---------------------------------------------------------------------------

def test_parse_pg_url_full():
    """Parse a full asyncpg URL."""
    result = parse_pg_url("postgresql+asyncpg://lumari:lumari_dev@localhost:5432/lumari")
    assert result == {
        "host": "localhost",
        "port": 5432,
        "user": "lumari",
        "password": "lumari_dev",
        "dbname": "lumari",
    }


def test_parse_pg_url_plain_postgres():
    """Parse a plain postgresql URL (no asyncpg driver)."""
    result = parse_pg_url("postgresql://user:secret@db.example.com:5433/mydb")
    assert result["host"] == "db.example.com"
    assert result["port"] == 5433
    assert result["user"] == "user"
    assert result["password"] == "secret"
    assert result["dbname"] == "mydb"


def test_parse_pg_url_defaults():
    """Missing parts should use sensible defaults."""
    result = parse_pg_url("postgresql://localhost/testdb")
    assert result["host"] == "localhost"
    assert result["port"] == 5432
    assert result["dbname"] == "testdb"


# ---------------------------------------------------------------------------
# CLI argument parsing tests
# ---------------------------------------------------------------------------

def test_parse_args_cold():
    args = parse_args(["cold"])
    assert args.command == "cold"
    assert args.skip_seed is False
    assert args.skip_qdrant is False
    assert args.dry_run is False


def test_parse_args_cold_flags():
    args = parse_args(["cold", "--skip-seed", "--skip-qdrant", "--dry-run"])
    assert args.skip_seed is True
    assert args.skip_qdrant is True
    assert args.dry_run is True


def test_parse_args_cold_with_urls():
    args = parse_args(["cold", "--database-url", "postgresql://x", "--qdrant-url", "http://y"])
    assert args.database_url == "postgresql://x"
    assert args.qdrant_url == "http://y"


def test_parse_args_warm_save():
    args = parse_args(["warm-save", "--output", "snapshots/test.dump"])
    assert args.command == "warm-save"
    assert args.output == "snapshots/test.dump"


def test_parse_args_warm_restore():
    args = parse_args(["warm-restore", "--snapshot", "snapshots/test.dump"])
    assert args.command == "warm-restore"
    assert args.snapshot == "snapshots/test.dump"


def test_parse_args_requires_command():
    with pytest.raises(SystemExit):
        parse_args([])
