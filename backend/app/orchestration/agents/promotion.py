import logging
from datetime import datetime, timezone

from app.models.sql.versioned_models import Agent

logger = logging.getLogger(__name__)


class AgentPromotion:
    """
    Befördert provisorische Agents zu permanenten Pool-Mitgliedern.

    Wenn ein auto-generierter Agent in einer Execution erfolgreich eingesetzt wurde
    (Verification Score >= Schwellwert), wird er permanent aktiviert.
    Zukünftige TeamAssembler-Calls sehen ihn als gleichwertigen Kandidaten.
    """

    def __init__(self, session_factory, min_score: float = 0.7):
        self.session_factory = session_factory
        self.min_score = min_score

    async def evaluate_and_promote(
        self,
        execution_results: dict,
        verification_score: float,
        team_plan: "TeamPlan",
    ) -> list[str]:
        """
        Prüft ob provisorische Agents im Team befördert werden sollen.

        Kriterien:
        - Execution war erfolgreich (Verification Score >= min_score)
        - Agent hat tatsächlich zum Ergebnis beigetragen (nicht übersprungen)
        - Agent ist als provisional/auto_generated markiert
        """
        if verification_score < self.min_score:
            return []

        promoted = []
        async with self.session_factory() as db:
            for planned_agent in team_plan.agents:
                agent = await db.get(Agent, planned_agent.agent_id)
                if not agent:
                    continue

                meta = agent.agent_metadata or {}
                if not meta.get("provisional"):
                    continue

                agent_result = self._find_agent_result(
                    execution_results, planned_agent.name
                )
                if not agent_result or not agent_result.get("success"):
                    continue

                meta.pop("provisional", None)
                runs = meta.get("successful_runs", 0) + 1
                total = meta.get("total_runs", 0) + 1
                meta["successful_runs"] = runs
                meta["total_runs"] = total
                meta["promotion_score"] = runs / total
                meta["promoted_at"] = datetime.now(timezone.utc).isoformat()
                agent.agent_metadata = meta

                await db.commit()
                promoted.append(agent.name)
                logger.info(f"Agent '{agent.name}' befördert: provisional → permanent")

        return promoted

    @staticmethod
    def _find_agent_result(results: dict, agent_name: str) -> dict | None:
        """Findet das Ergebnis eines Agents in den Wave-Results."""
        for wave_key, wave_data in results.items():
            if isinstance(wave_data, dict) and agent_name in wave_data:
                return wave_data[agent_name]
        return None
