"""Prompts für den LLM-basierten Team-Planner."""

TEAM_PLANNER_SYSTEM = """Du bist ein Team-Planner für ein Multi-Agent-System.
Dein Ziel: ein VOLLSTÄNDIGES Team zusammenstellen, bei dem die Datenfluss-Kette lückenlos ist.
Antworte nur mit JSON."""

TEAM_PLANNER_PROMPT = """Stelle ein Agent-Team für die folgende Aufgabe zusammen.

## Aufgabe
{challenge_text}

## Verfügbare Agents (nur aus diesem Pool wählen!)
{available_agents}

## Datenfluss-Regeln (KRITISCH — Verstöße führen zu Execution-Fehlern!)
1. Jeder Agent listet "Konsumiert" und "Produziert" Artifacts
2. Wenn ein Agent ein Artifact KONSUMIERT, MUSS ein anderer Agent im Team dieses Artifact PRODUZIEREN
3. Trace den Datenfluss von Input bis zum Endergebnis — es darf KEINE Lücke geben
4. Eine typische Pipeline hat die Form: Analyse → Verarbeitung → Validierung → Finalisierung
5. Wenn die Aufgabe unstrukturierten Text verarbeitet (Transkript, Protokoll, Notizen), braucht das Team IMMER einen Analyse-Agent der die Rohdaten strukturiert

## Datenfluss-Check (führe diesen vor der Antwort gedanklich durch)
Für jeden Agent im geplanten Team:
  - Liste seine konsumierten Artifacts auf
  - Prüfe: Wird jedes konsumierte Artifact von einem anderen Agent im Team produziert?
  - Wenn NEIN → füge den produzierenden Agent hinzu oder ersetze den Plan

## Regeln
1. Wähle NUR Agents die in der Liste oben stehen — erfinde keine neuen
2. Wenn keine passenden Fähigkeiten existieren, liste sie unter "missing_capabilities"
3. Definiere klare Dependencies (welcher Agent wartet auf welchen)
4. Der letzte Agent in der Kette muss das Endergebnis produzieren
5. Wähle die RICHTIGE Teamgröße für die Aufgabe — nicht künstlich klein, nicht unnötig groß
6. Nutze NUR Agents die zur Aufgabe beitragen (keine Developer-Team Agents für Execution-Tasks)
7. Bevorzuge Agents mit passenden Skills gegenüber generischen Agents

## Erfahrungen aus früheren Executions
{past_experiences}

## Antwortformat (JSON)
```json
{{
    "agents": [
        {{
            "agent_id": "uuid-des-agents",
            "name": "agent_name",
            "role": "Aufgabenspezifische Rolle",
            "dependencies": ["name_des_vorgelagerten_agents"],
            "produces_artifacts": ["artifact_type"],
            "consumes_artifacts": ["artifact_type"]
        }}
    ],
    "missing_capabilities": [],
    "rationale": "Begründung mit Datenfluss-Erklärung",
    "strategy": "Schritt-für-Schritt Verarbeitungskette"
}}
```

Antworte NUR mit dem JSON-Block."""


TEAM_REPLANNER_PROMPT = """Der vorherige Lösungsansatz hat nicht funktioniert. Erstelle einen NEUEN Plan mit einer ANDEREN Strategie.

## Aufgabe
{challenge_text}

## Vorheriger Ansatz (gescheitert)
Strategie: {previous_strategy}
Team: {previous_team}
Ergebnis: Score {previous_score}/1.0
Feedback: {verification_feedback}

## Verfügbare Agents
{available_agents}

## Regeln
1. Wähle einen ANDEREN Ansatz als "{previous_strategy}"
2. Wenn der vorherige Ansatz an fehlenden Fähigkeiten scheiterte, berücksichtige ob inzwischen neue Agents/Skills im Pool sind
3. Prüfe den Datenfluss: Jedes konsumierte Artifact muss von einem Agent im Team produziert werden
4. Wenn der Score 0.0 war, fehlte wahrscheinlich ein Analyse-Agent der die Rohdaten strukturiert

## Erfahrungen aus früheren Executions
{past_experiences}

Antworte im selben JSON-Format wie oben."""


def format_agent_pool(agents, skills_by_agent: dict[str, list]) -> str:
    """Formatiert den Agent-Pool kompakt und datenfluss-fokussiert."""
    lines = []
    for agent in agents:
        meta = agent.agent_metadata or {}
        team = meta.get("team", "unknown")

        consumes = agent.io_schema.get("consumes", []) if agent.io_schema else []
        produces = agent.io_schema.get("produces", []) if agent.io_schema else []

        capabilities = meta.get("capabilities", [])
        if not capabilities and agent.io_schema:
            cap_from_io = agent.io_schema.get("capabilities", [])
            if cap_from_io:
                capabilities = cap_from_io

        agent_skills = skills_by_agent.get(agent.id, [])
        relevant_skills = [
            s for s in agent_skills
            if _is_skill_specific_to_agent(s, agent.id)
        ]

        if relevant_skills:
            skill_info = ", ".join(
                s.name.replace("skill_", "").replace("_", " ")
                for s in relevant_skills[:5]
            )
        else:
            skill_info = "generische Skills"

        source_tag = f" [{team}]"
        if meta.get("auto_generated"):
            source_tag += " [auto-generiert]"
        if meta.get("promotion_score"):
            source_tag += f" [Erfolgsrate: {meta['promotion_score']:.0%}]"

        lines.append(
            f"### {agent.name} (ID: {agent.id}){source_tag}\n"
            f"  Konsumiert: {consumes}\n"
            f"  Produziert: {produces}\n"
            f"  Skills: {skill_info}"
        )
    return "\n".join(lines)


def _is_skill_specific_to_agent(skill, agent_id: str) -> bool:
    """Prüft ob ein Skill einem bestimmten Agent zugewiesen ist (nicht global)."""
    target = (skill.skill_metadata or {}).get("target_agent_id")
    return target is not None and target == agent_id
