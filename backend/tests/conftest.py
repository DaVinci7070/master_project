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
from sqlalchemy.pool import NullPool

from app.models.sql.base import Base
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
    Create a test database engine with NullPool.

    NullPool ensures each connection is closed immediately after use,
    preventing connection reuse issues in tests. This is the recommended
    approach per SQLAlchemy async documentation.

    Uses SQLite in-memory database for fast, isolated tests.
    """
    # Use in-memory SQLite for tests
    # aiosqlite required for async SQLite
    database_url = "sqlite+aiosqlite:///:memory:"

    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        echo=False,  # Set True for SQL debugging
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create a test database session.

    Each test gets a fresh session that rolls back after the test,
    ensuring test isolation.
    """
    async_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with async_session_factory() as session:
        yield session
        # Rollback any uncommitted changes
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
