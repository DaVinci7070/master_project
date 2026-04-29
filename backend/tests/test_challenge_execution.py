"""
Tests for Phase 12: End-to-End Execution Connection.

Tests the challenge submission → assessment → execution → results flow.
"""
import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.sql.intervention_models import BlockedChallenge
from app.dependencies.dependencies import get_db_session


@pytest.fixture(autouse=True)
def mock_db_session():
    """Mock database session — autouse um DB-Verbindung zu verhindern."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    # execute().scalar_one_or_none() für Lookups
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    yield session
    app.dependency_overrides.clear()


@pytest.fixture
def sample_challenge():
    """Sample challenge for testing."""
    return BlockedChallenge(
        id=str(uuid.uuid4()),
        execution_id=str(uuid.uuid4()),
        project_id="default",
        challenge_text="Analyze quarterly sales data",
        assessment_result={
            "confidence": "CAN_DO",
            "reasoning": "System can handle this",
            "top_factors": ["Skills available"],
            "gaps": [],
            "improvement_suggestions": [],
        },
        gaps_snapshot=[],
        status="assessed",
        attempt_number=1,
        max_attempts=5,
        built_capability_ids=[],
        failure_reasons=[],
        execution_results=None,
        created_at=datetime.now(timezone.utc),
    )


class TestChallengeAnalysis:
    """Tests for POST /challenges/analyze endpoint."""

    @pytest.mark.asyncio
    async def test_analyze_simple_challenge_returns_can_do(self):
        """Simple challenges should return CAN_DO confidence."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/challenges/analyze",
                json={
                    "challenge_text": "Hello world",
                    "execution_id": str(uuid.uuid4()),
                    "project_id": "default",
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert "challenge_id" in data
        assert data["assessment"]["confidence"] == "CAN_DO"
        assert data["route_decision"] == "execute"

    @pytest.mark.asyncio
    async def test_analyze_technical_challenge_returns_maybe(self):
        """Technical challenges should return MAYBE confidence."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/challenges/analyze",
                json={
                    "challenge_text": "Deploy the API server with authentication and database connection",
                    "execution_id": str(uuid.uuid4()),
                    "project_id": "default",
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert data["assessment"]["confidence"] == "MAYBE"
        assert data["route_decision"] == "developer_team"

    @pytest.mark.asyncio
    async def test_analyze_returns_challenge_id(self):
        """Analysis response should include challenge_id for execution."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/challenges/analyze",
                json={
                    "challenge_text": "Test challenge",
                    "execution_id": str(uuid.uuid4()),
                    "project_id": "default",
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert "challenge_id" in data
        assert len(data["challenge_id"]) == 36  # UUID format


class TestChallengeExecution:
    """Tests for POST /challenges/{id}/execute endpoint."""

    @pytest.mark.asyncio
    async def test_execute_assessed_challenge(self):
        """Executing an assessed challenge should start background task."""
        # First analyze
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            analyze_response = await client.post(
                "/api/v1/challenges/analyze",
                json={
                    "challenge_text": "Simple task",
                    "execution_id": str(uuid.uuid4()),
                    "project_id": "default",
                }
            )
            challenge_id = analyze_response.json()["challenge_id"]

            # Then execute
            execute_response = await client.post(
                f"/api/v1/challenges/{challenge_id}/execute"
            )

        assert execute_response.status_code == 200
        data = execute_response.json()
        assert data["challenge_id"] == challenge_id
        assert data["status"] == "executing"
        assert data["message"] == "Execution started"

    @pytest.mark.asyncio
    async def test_execute_nonexistent_challenge_returns_404(self):
        """Executing non-existent challenge should return 404."""
        fake_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/v1/challenges/{fake_id}/execute"
            )

        assert response.status_code == 404


class TestChallengeResults:
    """Tests for GET /challenges/{id}/results endpoint."""

    @pytest.mark.asyncio
    async def test_get_results_before_execution_returns_400(self):
        """Getting results before execution should return 400."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # Analyze but don't execute
            analyze_response = await client.post(
                "/api/v1/challenges/analyze",
                json={
                    "challenge_text": "Test",
                    "execution_id": str(uuid.uuid4()),
                    "project_id": "default",
                }
            )
            challenge_id = analyze_response.json()["challenge_id"]

            # Try to get results
            results_response = await client.get(
                f"/api/v1/challenges/{challenge_id}/results"
            )

        assert results_response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_results_nonexistent_returns_404(self):
        """Getting results for non-existent challenge returns 404."""
        fake_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/challenges/{fake_id}/results"
            )

        assert response.status_code == 404


class TestChallengeByExecutionId:
    """Tests for GET /challenges/by-execution/{execution_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_challenge_by_execution_id(self):
        """Should find challenge by execution_id."""
        execution_id = str(uuid.uuid4())

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # Create challenge
            analyze_response = await client.post(
                "/api/v1/challenges/analyze",
                json={
                    "challenge_text": "Test",
                    "execution_id": execution_id,
                    "project_id": "default",
                }
            )

            # Find by execution_id
            response = await client.get(
                f"/api/v1/challenges/by-execution/{execution_id}"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["execution_id"] == execution_id

    @pytest.mark.asyncio
    async def test_get_challenge_by_nonexistent_execution_id_returns_404(self):
        """Non-existent execution_id should return 404."""
        fake_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/challenges/by-execution/{fake_id}"
            )

        assert response.status_code == 404


class TestChallengeStatus:
    """Tests for GET /challenges/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_challenge_status_includes_execution_results(self):
        """Status response should include execution_results field."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # Create challenge
            analyze_response = await client.post(
                "/api/v1/challenges/analyze",
                json={
                    "challenge_text": "Test",
                    "execution_id": str(uuid.uuid4()),
                    "project_id": "default",
                }
            )
            challenge_id = analyze_response.json()["challenge_id"]

            # Get status
            response = await client.get(f"/api/v1/challenges/{challenge_id}")

        assert response.status_code == 200
        data = response.json()
        assert "execution_results" in data
        assert "status" in data


class TestEndToEndFlow:
    """Integration tests for full execution flow."""

    @pytest.mark.asyncio
    async def test_full_flow_analyze_execute_status(self):
        """Test complete flow: analyze → execute → check status."""
        execution_id = str(uuid.uuid4())

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # 1. Analyze
            analyze_response = await client.post(
                "/api/v1/challenges/analyze",
                json={
                    "challenge_text": "Generate a simple report",
                    "execution_id": execution_id,
                    "project_id": "default",
                }
            )
            assert analyze_response.status_code == 200
            challenge_id = analyze_response.json()["challenge_id"]
            route_decision = analyze_response.json()["route_decision"]

            # 2. Execute (only if route_decision is 'execute')
            if route_decision == "execute":
                execute_response = await client.post(
                    f"/api/v1/challenges/{challenge_id}/execute"
                )
                assert execute_response.status_code == 200
                assert execute_response.json()["status"] == "executing"

            # 3. Check status
            status_response = await client.get(
                f"/api/v1/challenges/{challenge_id}"
            )
            assert status_response.status_code == 200
            status = status_response.json()["status"]
            assert status in ["assessed", "executing", "resolved", "failed"]
