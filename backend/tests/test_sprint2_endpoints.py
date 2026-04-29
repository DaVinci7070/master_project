"""
Sprint 2 tests for F6 Evolution-API endpoints:
- GET /api/v1/skills/{id}/version-history  (lineage + build attempts)
- GET /api/v1/topology/history  (with previous_state / new_state)
"""
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport

# Make sure models register with Base.metadata (conftest already imports them,
# but be explicit in case of collection order surprises).
from app.models.sql import versioned_models, skill_build_models, topology_models  # noqa: F401

from app.main import app
from app.dependencies.dependencies import get_db_session
from app.models.sql.versioned_models import Skill
from app.models.sql.skill_build_models import SkillBuildAttempt
from app.models.sql.topology_models import TopologyChangeLog


@pytest.fixture
def app_with_session(test_session):
    """Bind the FastAPI app to the test_session DB."""
    async def _override():
        yield test_session

    app.dependency_overrides[get_db_session] = _override
    yield app
    app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------------------
# Skill version-history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_version_history_returns_lineage(app_with_session, test_session):
    """Lineage is returned root → requested with version_index ascending."""
    root = Skill(id="skill-root-0000000000000000000000000", name="root-v1",
                 skill_type="functional", is_active=False, parent_id=None)
    v2 = Skill(id="skill-v2-00000000000000000000000000000", name="root-v2",
               skill_type="functional", is_active=False, parent_id=root.id)
    v3 = Skill(id="skill-v3-00000000000000000000000000000", name="root-v3",
               skill_type="functional", is_active=True, parent_id=v2.id)
    test_session.add_all([root, v2, v3])
    await test_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_with_session), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/skills/{v3.id}/version-history")

    assert resp.status_code == 200
    body = resp.json()
    assert body["skill_id"] == v3.id
    assert body["total_versions"] == 3
    # root first, requested last
    ids = [entry["id"] for entry in body["lineage"]]
    assert ids == [root.id, v2.id, v3.id]
    indices = [entry["version_index"] for entry in body["lineage"]]
    assert indices == [1, 2, 3]


@pytest.mark.asyncio
async def test_skill_version_history_includes_build_attempts(
    app_with_session, test_session
):
    """Each version carries its SkillBuildAttempt records."""
    skill = Skill(id="skill-build-0000000000000000000000000", name="built",
                  skill_type="functional", is_active=True, parent_id=None)
    attempt = SkillBuildAttempt(
        id="att-build-000000000000000000000000000000",
        capability="parse-csv",
        attempt_number=1,
        success=False,
        error_type="import_error",
        error_type_classified="IMPORT_ERROR",
        lesson_learned="module 'xyz' not installed; use pandas",
        failure_analysis={"root_cause": "missing-dep"},
        code_snapshot="def execute(data): return data",
        skill_id=skill.id,
    )
    test_session.add_all([skill, attempt])
    await test_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_with_session), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/skills/{skill.id}/version-history")

    assert resp.status_code == 200
    body = resp.json()
    entry = body["lineage"][0]
    assert len(entry["build_attempts"]) == 1
    att = entry["build_attempts"][0]
    assert att["attempt_number"] == 1
    assert att["success"] is False
    assert att["error_type_classified"] == "IMPORT_ERROR"
    assert "pandas" in att["lesson_learned"]
    assert att["failure_analysis"] == {"root_cause": "missing-dep"}


@pytest.mark.asyncio
async def test_skill_version_history_404_for_unknown(app_with_session):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_session), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/skills/does-not-exist/version-history")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Topology history with before/after snapshots
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_topology_history_exposes_previous_and_new_state(
    app_with_session, test_session
):
    """/topology/history now exposes previous_state and new_state snapshots."""
    log = TopologyChangeLog(
        id="tc-0000000000000000000000000000000000",
        change_type="agent_updated",
        entity_type="agent",
        entity_id="agent-1",
        entity_name="Planner",
        source="system",
        triggered_by="challenge-xyz",
        change_details={"reason": "self-heal"},
        previous_state={"role": "planner", "prompt_version": 1},
        new_state={"role": "planner", "prompt_version": 2},
    )
    test_session.add(log)
    await test_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_with_session), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/topology/history?limit=10")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    entry = next(e for e in body["entries"] if e["id"] == log.id)
    assert entry["entity_type"] == "agent"
    assert entry["entity_name"] == "Planner"
    assert entry["source"] == "system"
    assert entry["triggered_by"] == "challenge-xyz"
    assert entry["previous_state"] == {"role": "planner", "prompt_version": 1}
    assert entry["new_state"] == {"role": "planner", "prompt_version": 2}
    assert entry["change_details"] == {"reason": "self-heal"}
