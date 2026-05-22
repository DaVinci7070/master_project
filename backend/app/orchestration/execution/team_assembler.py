"""Stellt aufgabenspezifische Agent-Teams per LLM zusammen."""
import json
import logging
import re
from typing import Any, Optional

from app.models.schemas.team_schemas import (
    GapReport,
    MissingCapability,
    PlannedAgent,
    PlanValidation,
    TeamPlan,
    VerificationResult,
)
from app.prompts.team_planner_prompt import (
    TEAM_PLANNER_PROMPT,
    TEAM_PLANNER_SYSTEM,
    TEAM_REPLANNER_PROMPT,
    format_agent_pool,
)

logger = logging.getLogger(__name__)


_DEV_TEAM_NAMES = frozenset({
    "product_owner", "control_agent", "prompt_engineer",
    "tool_builder", "quality_judge", "execution_analyzer",
})


class TeamAssembler:
    """
    Stellt aufgabenspezifische Agent-Teams zusammen.

    Read-only auf DB — erstellt keine Agents oder Skills.
    Wenn Capabilities fehlen: gibt GapReport zurück.
    Nutzt SharedMemory für Strategie-Erfahrungen aus vergangenen Runs.
    """

    def __init__(self, session_factory, llm_client=None, shared_memory=None, settings=None):
        from app.core.config import settings as default_settings
        self.session_factory = session_factory
        self.llm = llm_client
        self.shared_memory = shared_memory
        self._settings = settings or default_settings

    async def assemble_team(
        self,
        challenge_text: str,
        available_agents: list,
        available_skills: list,
    ) -> TeamPlan | GapReport:
        """
        Team für eine Aufgabe zusammenstellen.

        1. SharedMemory nach Erfahrungen durchsuchen
        2. LLM plant Team aus verfügbarem Agent-Pool
        3. Plan validieren (Solvability, Completeness)
        4. Bei Validierungsfehlern: einmal nachbessern
        5. Capabilities fehlen → GapReport
        6. Alles da → TeamPlan mit berechneten Waves
        """
        available_agents = self._filter_execution_agents(available_agents)
        skills_by_agent = self._group_skills_by_agent(available_agents, available_skills)

        plan_or_gap = await self._plan_with_llm(
            challenge_text, available_agents, available_skills, skills_by_agent
        )

        if isinstance(plan_or_gap, GapReport):
            return plan_or_gap

        plan = plan_or_gap

        validation = self._validate_plan(plan, available_agents, available_skills)
        if not validation.valid:
            plan_or_gap = await self._plan_with_llm(
                challenge_text, available_agents, available_skills,
                skills_by_agent, feedback=validation.issues,
            )
            if isinstance(plan_or_gap, GapReport):
                return plan_or_gap
            plan = plan_or_gap

        plan.execution_waves = self._compute_waves(plan.agents)
        return plan

    async def replan_with_feedback(
        self,
        challenge_text: str,
        previous_plan: TeamPlan,
        verification: VerificationResult,
        available_agents: list,
        available_skills: list,
    ) -> TeamPlan | GapReport:
        """Neuer Plan nach gescheitertem Versuch mit anderer Strategie."""
        available_agents = self._filter_execution_agents(available_agents)
        skills_by_agent = self._group_skills_by_agent(available_agents, available_skills)
        past_experiences = await self._load_past_experiences(challenge_text)

        previous_team = ", ".join(a.name for a in previous_plan.agents)

        prompt = TEAM_REPLANNER_PROMPT.format(
            challenge_text=challenge_text,
            previous_strategy=previous_plan.strategy or "unbekannt",
            previous_team=previous_team,
            previous_score=f"{verification.score:.2f}",
            verification_feedback=verification.feedback_for_retry,
            available_agents=format_agent_pool(available_agents, skills_by_agent),
            past_experiences=past_experiences or "Keine früheren Erfahrungen.",
        )

        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": TEAM_PLANNER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=2000,
        )

        result = self._parse_response(response.content, challenge_text, available_agents)
        if isinstance(result, TeamPlan):
            result.execution_waves = self._compute_waves(result.agents)
        return result

    async def _plan_with_llm(
        self,
        challenge_text: str,
        agents: list,
        skills: list,
        skills_by_agent: dict[str, list],
        feedback: list[str] | None = None,
    ) -> TeamPlan | GapReport:
        """LLM plant die Team-Zusammensetzung."""
        past_experiences = await self._load_past_experiences(challenge_text)

        prompt = TEAM_PLANNER_PROMPT.format(
            challenge_text=challenge_text,
            available_agents=format_agent_pool(agents, skills_by_agent),
            past_experiences=past_experiences or "Keine früheren Erfahrungen verfügbar.",
        )

        if feedback:
            prompt += "\n\n## Korrektur-Feedback\nDein vorheriger Plan hatte Probleme:\n"
            prompt += "\n".join(f"- {f}" for f in feedback)
            prompt += "\nBitte korrigiere diese Probleme."

        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": TEAM_PLANNER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )

        return self._parse_response(response.content, challenge_text, agents)

    def _parse_response(
        self, content: str, challenge_text: str, agents: list,
    ) -> TeamPlan | GapReport:
        """Parsed LLM-Antwort zu TeamPlan oder GapReport."""
        data = json.loads(self._extract_json(content))
        name_to_agent = {a.name: a for a in agents}
        id_to_agent = {a.id: a for a in agents}

        missing = data.get("missing_capabilities", [])
        if missing:
            caps = []
            for m in missing:
                if isinstance(m, str):
                    caps.append(MissingCapability(
                        capability=m, description=m, rationale="LLM-reported gap",
                    ))
                elif isinstance(m, dict):
                    caps.append(MissingCapability(**m))
            return GapReport(
                challenge_text=challenge_text,
                missing_capabilities=caps,
                planner_rationale=data.get("rationale", ""),
            )

        planned_agents = []
        for a in data.get("agents", []):
            agent = id_to_agent.get(a.get("agent_id")) or name_to_agent.get(a.get("name"))
            if not agent:
                continue

            planned_agents.append(PlannedAgent(
                agent_id=agent.id,
                name=agent.name,
                role=a.get("role", ""),
                dependencies=a.get("dependencies", []),
                produces_artifacts=a.get("produces_artifacts", []),
                consumes_artifacts=a.get("consumes_artifacts", []),
            ))

        return TeamPlan(
            challenge_text=challenge_text,
            agents=planned_agents,
            rationale=data.get("rationale", ""),
            strategy=data.get("strategy", ""),
        )

    def _validate_plan(
        self,
        plan: TeamPlan,
        available_agents: list,
        available_skills: list,
    ) -> PlanValidation:
        """Validiert TeamPlan: Agents, Dependencies, Artifact-Datenfluss."""
        issues = []

        if not plan.agents:
            issues.append("Plan enthält keine Agents")
            return PlanValidation(valid=False, issues=issues)

        if len(plan.agents) > 8:
            issues.append(
                f"Team zu groß ({len(plan.agents)} Agents). "
                f"Max 6-8 — Coordination-Overhead überwiegt."
            )

        agent_ids = {a.id for a in available_agents}
        id_to_db_agent = {a.id: a for a in available_agents}
        for planned in plan.agents:
            if planned.agent_id not in agent_ids:
                issues.append(f"Agent '{planned.name}' (ID: {planned.agent_id}) existiert nicht im Pool")

        plan_names = {a.name for a in plan.agents}
        for planned in plan.agents:
            for dep in planned.dependencies:
                if dep not in plan_names:
                    issues.append(f"Agent '{planned.name}' hat Dependency auf '{dep}' der nicht im Plan ist")

        produced = set()
        for planned in plan.agents:
            db_agent = id_to_db_agent.get(planned.agent_id)
            if db_agent and db_agent.io_schema:
                for art in db_agent.io_schema.get("produces", []):
                    produced.add(art)
            for art in planned.produces_artifacts:
                produced.add(art)

        for planned in plan.agents:
            db_agent = id_to_db_agent.get(planned.agent_id)
            if not db_agent:
                continue
            required = set()
            if db_agent.io_schema:
                for art in db_agent.io_schema.get("consumes", []):
                    required.add(art)
            for art in planned.consumes_artifacts:
                required.add(art)

            for art in required:
                if art not in produced and art != "verification_feedback":
                    matching_producer = self._find_producer(art, available_agents)
                    if matching_producer:
                        issues.append(
                            f"DATENFLUSS-LÜCKE: '{planned.name}' konsumiert '{art}', "
                            f"aber kein Agent im Team produziert es. "
                            f"Füge '{matching_producer}' zum Team hinzu."
                        )
                    else:
                        issues.append(
                            f"DATENFLUSS-LÜCKE: '{planned.name}' konsumiert '{art}', "
                            f"aber kein Agent im Team produziert es."
                        )

        return PlanValidation(valid=len(issues) == 0, issues=issues)

    @staticmethod
    def _find_producer(artifact: str, available_agents: list) -> str | None:
        """Findet den Agent im Pool der ein bestimmtes Artifact produziert."""
        for agent in available_agents:
            if agent.io_schema:
                produces = agent.io_schema.get("produces", [])
                if artifact in produces:
                    return agent.name
        return None

    def _compute_waves(self, agents: list[PlannedAgent]) -> list[list[str]]:
        """Berechnet Execution-Waves aus Agent-Dependencies."""
        if not agents:
            return []

        from graphlib import TopologicalSorter

        dep_graph = {a.name: set(a.dependencies) for a in agents}
        ts = TopologicalSorter(dep_graph)
        order = list(ts.static_order())

        agent_wave: dict[str, int] = {}
        for name in order:
            deps = dep_graph.get(name, set())
            agent_wave[name] = (max(agent_wave.get(d, 0) for d in deps) + 1) if deps else 0

        max_wave = max(agent_wave.values(), default=0)
        waves: list[list[str]] = [[] for _ in range(max_wave + 1)]
        for name, wave in agent_wave.items():
            waves[wave].append(name)
        return waves

    @staticmethod
    def _filter_execution_agents(agents: list) -> list:
        """Developer-Team Agents herausfiltern — die gehören nicht in Execution-Pipelines."""
        filtered = [
            a for a in agents
            if a.name not in _DEV_TEAM_NAMES
            and (getattr(a, "agent_metadata", None) or {}).get("team") != "developer"
        ]
        if len(filtered) < len(agents):
            removed = len(agents) - len(filtered)
            logger.debug(f"Execution-Filter: {removed} Developer-Team Agent(s) entfernt")
        return filtered

    def _group_skills_by_agent(self, agents, skills) -> dict[str, list]:
        """Gruppiert Skills nach zugewiesenem Agent. Globale Skills bleiben unter 'global'."""
        result: dict[str, list] = {a.id: [] for a in agents}
        for skill in skills:
            target = (skill.skill_metadata or {}).get("target_agent_id")
            if target and target in result:
                result[target].append(skill)
        return result

    async def _load_past_experiences(self, challenge_text: str) -> str | None:
        """Lädt relevante Erfahrungen + Reflexionen aus SharedMemory."""
        if not self.shared_memory:
            return None

        try:
            from app.models.schemas.shared_memory_schemas import SharedMemoryQuery

            outcome_query = SharedMemoryQuery(
                query_text=f"team_plan execution strategy: {challenge_text[:200]}",
                max_items=3,
                score_threshold=0.3,
            )
            outcome_context = await self.shared_memory.retrieve_context(outcome_query)

            reflection_query = SharedMemoryQuery(
                query_text=f"execution reflection lesson: {challenge_text[:200]}",
                max_items=self._settings.reflection_memory_max_items,
                score_threshold=0.3,
                min_confidence=0.3,
                tags=["execution_reflection"],
            )
            reflection_context = await self.shared_memory.retrieve_context(reflection_query)

            lines = []

            outcomes = outcome_context.get("facts", [])
            if outcomes:
                lines.append("### Frühere Ergebnisse")
                for fact in outcomes[:3]:
                    payload = fact.get("text", "") if isinstance(fact, dict) else str(fact)
                    lines.append(f"- {payload}")

            reflections = reflection_context.get("facts", [])
            if reflections:
                lines.append("\n### Reflexionen aus gescheiterten Versuchen (BEACHTE DIESE!)")
                for fact in reflections[:3]:
                    payload = fact.get("text", "") if isinstance(fact, dict) else str(fact)
                    lines.append(f"- {payload}")

            return "\n".join(lines) if lines else None

        except Exception as e:
            logger.warning(f"SharedMemory-Abfrage fehlgeschlagen: {e}")
            return None

    @staticmethod
    def _extract_json(content: str) -> str:
        """Extrahiert JSON-Block aus LLM-Antwort."""
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1)
        return content.strip()
