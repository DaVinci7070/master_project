"""
Pytest configuration and fixtures for lumari-backend tests.

This module provides:
- Database fixtures with NullPool for test isolation
- Async test configuration
- Common test fixtures (skill_executor, etc.)
"""
import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.models.sql.base import Base
# Import SQL model modules so they register with Base.metadata before
# create_all() runs in the test_engine fixture. Excludes modules that use
# Postgres-only types (JSONB) incompatible with the SQLite test DB —
# those tables are not needed by the current test suite.
from app.models.sql import (  # noqa: F401
    sql_models,
    versioned_models,
    telemetry_models,
    analysis_models,
    improvement_models,
    ab_test_models,
    artifact_schema_models,
    skill_build_models,
    agent_event_models,
    shared_memory_models,
    execution_models,
    intervention_models,
    topology_models,
)
from app.services.skill_executor import SkillExecutor


# Configure pytest-asyncio
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """
    Create an event loop for the test session.

    Using session scope to share loop across all tests.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    Create a test database engine with StaticPool.

    SQLite ``:memory:`` databases are per-connection: each new connection
    opens a fresh, empty DB. With ``NullPool`` this means tables created by
    ``create_all()`` disappear before the next connection sees them.
    ``StaticPool`` holds a single shared connection for the lifetime of the
    engine, so all sessions observe the same in-memory DB.
    """
    # Use in-memory SQLite for tests
    # aiosqlite required for async SQLite
    database_url = "sqlite+aiosqlite:///:memory:"

    engine = create_async_engine(
        database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,  # Set True for SQL debugging
    )

    # Create all tables except those using Postgres-only types (JSONB),
    # which SQLite cannot compile. Those tables aren't needed by tests.
    def _is_sqlite_compatible(table) -> bool:
        for col in table.columns:
            type_name = type(col.type).__name__
            if type_name == "JSONB":
                return False
        return True

    tables = [t for t in Base.metadata.tables.values() if _is_sqlite_compatible(t)]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))

    yield engine

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.drop_all(sync_conn, tables=tables))

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_factory(test_engine: AsyncEngine):
    """Session-Factory für Tests — gibt eine Factory zurück, keine einzelne Session."""
    factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return factory


@pytest_asyncio.fixture(scope="function")
async def test_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """
    Create a test database session.

    Each test gets a fresh session that rolls back after the test,
    ensuring test isolation.
    """
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def skill_executor() -> SkillExecutor:
    """
    Create a SkillExecutor instance for testing.

    Uses a short timeout for faster test execution.
    """
    return SkillExecutor(timeout_seconds=2.0)


@pytest.fixture
def sample_skill_code() -> str:
    """Sample skill code for testing."""
    return '''
def execute(data):
    """Simple skill that doubles a number."""
    return data.get("value", 0) * 2
'''


@pytest.fixture
def sample_test_cases() -> list:
    """Sample test cases for testing."""
    return [
        {"input": {"value": 5}, "expected_output": 10},
        {"input": {"value": 0}, "expected_output": 0},
        {"input": {"value": -3}, "expected_output": -6},
    ]


@pytest.fixture
def dangerous_code_exec() -> str:
    """Code that tries to use exec (should be blocked)."""
    return '''
def execute(data):
    exec("x = 1")
    return x
'''


@pytest.fixture
def dangerous_code_import() -> str:
    """Code that tries to import os (should be blocked)."""
    return '''
import os
def execute(data):
    return os.getcwd()
'''


@pytest.fixture
def code_with_allowed_import() -> str:
    """Code that uses allowed imports."""
    return '''
import json
import math
from datetime import datetime

def execute(data):
    result = {
        "doubled": data.get("value", 0) * 2,
        "sqrt": math.sqrt(abs(data.get("value", 0))),
        "timestamp": datetime.now().isoformat()
    }
    return json.loads(json.dumps(result))
'''
