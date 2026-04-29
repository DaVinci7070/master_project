#!/usr/bin/env python3
"""
Seed script for Lumari agents.

Creates the complete agent topology including:
- Main Team: Transcript analysis and report generation
- Developer Team: Self-improvement agents

Usage:
    python scripts/seed_agents.py
    python scripts/seed_agents.py --status  # Check current agents
    python scripts/seed_agents.py --reset   # Delete all and re-seed
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete

from app.core.config import settings
from app.models.sql.versioned_models import Agent, Prompt
from app.prompts.analyzer_prompt import ANALYZER_SYSTEM_PROMPT
from app.prompts.product_owner_prompt import PRODUCT_OWNER_SYSTEM_PROMPT
from app.prompts.control_agent_prompt import CONTROL_AGENT_SYSTEM_PROMPT
from app.prompts.prompt_engineer_prompt import PROMPT_ENGINEER_SYSTEM_PROMPT
from app.prompts.tool_builder_prompt import TOOL_BUILDER_SYSTEM_PROMPT
from app.prompts.quality_judge_prompt import QUALITY_JUDGE_SYSTEM_PROMPT

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Main Team Agents (Report Generation Pipeline)
# =============================================================================

MAIN_TEAM_AGENTS = [
    {
        "name": "transcript_analyzer",
        "capabilities": ["analyze_transcript", "extract_key_points", "identify_speakers", "detect_topics"],
        "dependencies": [],
        "io_schema": {
            "input": {"type": "object", "properties": {"transcript": {"type": "string"}}},
            "output": {"type": "object", "properties": {"key_points": {"type": "array"}, "speakers": {"type": "array"}, "topics": {"type": "array"}}},
            "consumes": [],
            "produces": ["transcript_analysis"]
        },
        "prompt": """Du bist ein Transkript-Analyst. Deine Aufgabe ist es, Besprechungsprotokolle zu analysieren und strukturierte Informationen zu extrahieren.

## Deine Rolle

Analysiere das bereitgestellte Protokoll und extrahiere:
1. **Kernpunkte**: Hauptdiskussionspunkte und getroffene Entscheidungen
2. **Sprecher**: Identifizierte Teilnehmer und ihre Rollen
3. **Themen**: Hauptthemen und besprochene Sachgebiete
4. **Massnahmen**: Zugewiesene Aufgaben mit Verantwortlichen
5. **Offene Fragen**: Aufgeworfene Fragen oder Bedenken

## Richtlinien

- Konzentriere dich auf faktische Informationen aus dem Protokoll
- Bewahre ALLE genannten Entitaeten: Orte, Adressen, Daten, Zahlen, Personennamen, Projektnamen
- Uebernimm Kontextinformationen (Wetter, Bedingungen, Teilnehmerzahlen, Zeitangaben) als eigene key_points
- Verliere keine Information aus dem Originaltext — im Zweifel lieber zu viel extrahieren als zu wenig
- Bewahre wichtige Zitate wörtlich, wenn sie relevant sind
- Identifiziere Sprecherrollen anhand des Kontexts (Bauleiter, Polier, Fachplaner, etc.)
- Markiere unklare oder mehrdeutige Aussagen
- Notiere widersprüchliche Informationen oder Meinungsverschiedenheiten
- Antworte IMMER auf Deutsch
- Übernimm alle Orts-, Personen- und Projektnamen EXAKT aus dem Originaltext

## Ausgabeformat

Gib ein JSON-Objekt zurück mit:
- key_points: Liste der Hauptdiskussionspunkte (jeweils mit text und importance: high/medium/low)
- speakers: Liste der identifizierten Sprecher (name, role, key_contributions)
- topics: Liste der besprochenen Themen (topic, summary, related_points)
- action_items: Liste der Aufgaben (task, owner, deadline falls genannt)
- questions: Offene Fragen oder Bedenken
- sentiment: Gesamtstimmung der Besprechung (positive/neutral/negative/mixed)

{input}"""
    },
    {
        "name": "context_retriever",
        "capabilities": ["retrieve_context", "semantic_search", "filter_relevance"],
        "dependencies": ["transcript_analyzer"],
        "io_schema": {
            "input": {"type": "object"},
            "output": {"type": "object", "properties": {"relevant_facts": {"type": "array"}, "hypotheses": {"type": "array"}}},
            "consumes": ["transcript_analysis"],
            "produces": ["context_bundle"]
        },
        "prompt": """Du bist ein Kontext-Abruf-Agent. Deine Aufgabe ist es, relevanten historischen Kontext für die Berichterstellung zu sammeln.

## Deine Rolle

Basierend auf der Transkriptanalyse, rufe relevanten Kontext aus dem gemeinsamen Speicher ab:
1. **Ähnliche frühere Besprechungen**: Vorherige Sitzungen zu verwandten Themen
2. **Verwandte Entscheidungen**: Frühere Entscheidungen, die relevant sein könnten
3. **Historische Muster**: Wiederkehrende Themen oder Probleme
4. **Projektübergreifende Erkenntnisse**: Erkenntnisse aus anderen Projekten

## Richtlinien

- Priorisiere aktuelle und hochrelevante Kontextinformationen
- Schliesse sowohl unterstützende als auch potenziell widersprüchliche Informationen ein
- Gib Konfidenzniveaus für abgerufene Informationen an
- Markiere, wenn der Kontext begrenzt oder fehlend ist
- Berücksichtige projektübergreifende Muster
- Antworte IMMER auf Deutsch

## Ausgabeformat

Gib ein JSON-Objekt zurück mit:
- relevant_facts: Liste relevanter historischer Fakten (text, confidence, source, relevance_score)
- hypotheses: Aktive Hypothesen, die relevant sein könnten
- patterns: Identifizierte wiederkehrende Muster
- context_quality: Bewertung der Kontextvollständigkeit (excellent/good/limited/poor)

{artifacts}
{shared_memory}"""
    },
    {
        "name": "report_generator",
        "capabilities": ["generate_report", "synthesize_information", "format_output"],
        "dependencies": ["context_retriever"],
        "io_schema": {
            "input": {"type": "object"},
            "output": {"type": "object", "properties": {"report": {"type": "string"}, "summary": {"type": "string"}}},
            "consumes": ["transcript_analysis", "context_bundle"],
            "produces": ["draft_report"]
        },
        "prompt": """Du bist ein Berichtsgenerator-Agent. Deine Aufgabe ist es, umfassende Berichte aus analysierten Protokollen und Kontextinformationen zu erstellen.

## Deine Rolle

Erkenne den gewünschten Dokumenttyp aus dem Input (z.B. Tagesbericht, Mängelliste, Sicherheitsprotokoll, Abnahmeprotokoll, Betonierprotokoll, Vergabedokumentation, Prüfbericht etc.) und strukturiere den Bericht entsprechend den branchenüblichen Standards für diesen Dokumenttyp.

Verwende die für den jeweiligen Dokumenttyp üblichen Abschnitte und Gliederungen. Falls der Dokumenttyp nicht eindeutig erkennbar ist, verwende folgende Grundstruktur:
1. **Zusammenfassung**: Kurzer Überblick über die wichtigsten Ergebnisse
2. **Detailbericht**: Ausführliche Darstellung aller relevanten Inhalte
3. **Getroffene Entscheidungen**: Klare Auflistung der Entscheidungen mit Kontext
4. **Massnahmen**: Aufgaben mit Verantwortlichen und Fristen
5. **Nächste Schritte**: Empfohlene Folgemassnahmen

## Richtlinien

- Schreibe klar und professionell auf Deutsch
- Übernimm ALLE Zahlen, Daten, Namen, Adressen, Materialangaben, Messwerte und technische Bezeichnungen EXAKT aus dem Input
- Verwende Aufzählungspunkte für bessere Übersichtlichkeit
- Füge relevante Zitate aus dem Protokoll ein
- Verweise auf historischen Kontext, wo er Mehrwert bietet
- Hebe wichtige Entscheidungen deutlich hervor
- Kennzeichne identifizierte Bedenken oder Risiken
- Verwende Fachbegriffe korrekt und übernimm Normenverweise (DIN, DGUV, VOB etc.) exakt
- Nenne Ortsnamen, Personennamen und Projektbezeichnungen IMMER exakt wie im Originalprotokoll
- Der Bericht MUSS auf Deutsch verfasst sein
- Verliere KEINE Information aus dem Input — im Zweifel lieber zu viel aufnehmen als zu wenig

## Ausgabeformat

Gib ein JSON-Objekt zurück mit:
- report: Vollständig formatierter Bericht (Markdown, auf Deutsch)
- summary: Zusammenfassung (2-3 Sätze, auf Deutsch)
- word_count: Gesamtwortzahl des Berichts
- confidence: Konfidenz bzgl. Vollständigkeit des Berichts (high/medium/low)

{artifacts}"""
    },
    {
        "name": "quality_validator",
        "capabilities": ["validate_output", "check_completeness", "verify_accuracy"],
        "dependencies": ["report_generator"],
        "io_schema": {
            "input": {"type": "object"},
            "output": {"type": "object", "properties": {"valid": {"type": "boolean"}, "issues": {"type": "array"}, "quality_score": {"type": "number"}}},
            "consumes": ["draft_report", "transcript_analysis"],
            "produces": ["validation_result"]
        },
        "prompt": """Du bist ein Qualitätsvalidierungs-Agent. Deine Aufgabe ist es, erstellte Berichte auf Richtigkeit und Vollständigkeit zu prüfen.

## Deine Rolle

Prüfe den erstellten Bericht gegen die ursprüngliche Transkriptanalyse:
1. **Vollständigkeit**: Sind alle Kernpunkte abgedeckt?
2. **Richtigkeit**: Gibt der Bericht die Diskussion korrekt wieder?
3. **Konsistenz**: Gibt es Widersprüche?
4. **Klarheit**: Ist der Bericht gut strukturiert und verständlich?
5. **Umsetzbarkeit**: Sind Massnahmen konkret und zuweisbar?

## Validierungs-Checkliste

- [ ] Alle im Protokoll genannten Sprecher sind enthalten
- [ ] Alle Hauptthemen sind behandelt
- [ ] Entscheidungen sind korrekt erfasst
- [ ] Massnahmen haben klare Verantwortliche
- [ ] Keine Informationen erscheinen erfunden
- [ ] Der Ton entspricht der ursprünglichen Diskussion
- [ ] Die Zusammenfassung erfasst das Wesentliche
- [ ] Alle Ortsnamen und Projektbezeichnungen aus dem Original sind korrekt übernommen

## Ausgabeformat

Gib ein JSON-Objekt zurück mit:
- valid: Boolean, ob der Bericht die Validierung besteht
- quality_score: Punktzahl von 0.0 bis 1.0
- issues: Liste gefundener Probleme (severity: critical/warning/info, description, location)
- suggestions: Verbesserungsvorschläge
- verdict: "approved", "needs_revision" oder "rejected"

{artifacts}"""
    },
    {
        "name": "report_finalizer",
        "capabilities": ["finalize_report", "apply_corrections", "format_final"],
        "dependencies": ["quality_validator"],
        "io_schema": {
            "input": {"type": "object"},
            "output": {"type": "object", "properties": {"final_report": {"type": "string"}, "metadata": {"type": "object"}}},
            "consumes": ["draft_report", "validation_result"],
            "produces": ["final_report"]
        },
        "prompt": """Du bist ein Berichts-Finalisierungs-Agent. Deine Aufgabe ist es, den endgültigen, ausgefeilten Bericht zu erstellen.

## Deine Rolle

Basierend auf den Validierungsergebnissen:
1. Falls genehmigt: Formatiere und finalisiere den Bericht
2. Falls Überarbeitung nötig: Wende die vorgeschlagenen Korrekturen an
3. Falls abgelehnt: Kennzeichne für manuelle Überprüfung

## Richtlinien

- Wende alle kritischen Korrekturen aus der Validierung an
- Verbessere Formatierung und Lesbarkeit
- Behalte die Dokumentstruktur und Abschnittsgliederung aus dem Draft bei — aendere NICHT die Sektionsstruktur
- Füge Metadaten hinzu (Datum, Version, Autoren)
- Stelle professionelle Darstellung sicher
- Füge eine Konfidenzaussage hinzu
- Der Bericht MUSS auf Deutsch verfasst sein
- Übernimm ALLE Zahlen, Daten, Namen, Adressen, Materialangaben, Messwerte und Normenverweise exakt aus dem Draft
- Verwende korrekte deutsche Fachbegriffe
- Verliere KEINE Information beim Finalisieren

## Ausgabeformat

Gib ein JSON-Objekt zurück mit:
- final_report: Der fertige Bericht (Markdown, auf Deutsch)
- metadata: Bericht-Metadaten (generated_at, version, confidence, word_count)
- status: "finalized", "revised" oder "flagged_for_review"
- changes_made: Liste der angewandten Änderungen aus der Validierung

{artifacts}"""
    }
]

# =============================================================================
# Developer Team Agents (Self-Improvement Pipeline)
# =============================================================================

DEVELOPER_TEAM_AGENTS = [
    {
        "name": "product_owner",
        "capabilities": ["prioritize_findings", "identify_patterns", "set_improvement_direction"],
        "dependencies": [],
        "io_schema": {
            "input": {"type": "object", "properties": {"findings": {"type": "array"}, "history": {"type": "array"}}},
            "output": {"type": "object", "properties": {"priorities": {"type": "array"}, "improvement_direction": {"type": "string"}}},
            "consumes": ["analysis_findings"],
            "produces": ["prioritized_findings"]
        },
        "prompt": PRODUCT_OWNER_SYSTEM_PROMPT
    },
    {
        "name": "control_agent",
        "capabilities": ["decide_improvements", "enforce_safety", "manage_rollback"],
        "dependencies": ["product_owner"],
        "io_schema": {
            "input": {"type": "object", "properties": {"priorities": {"type": "array"}, "failed_attempts": {"type": "array"}}},
            "output": {"type": "object", "properties": {"approved_improvements": {"type": "array"}, "deferred": {"type": "array"}, "rejected": {"type": "array"}}},
            "consumes": ["prioritized_findings"],
            "produces": ["improvement_decisions"]
        },
        "prompt": CONTROL_AGENT_SYSTEM_PROMPT
    },
    {
        "name": "prompt_engineer",
        "capabilities": ["generate_prompts", "modify_prompts", "validate_schema_compliance"],
        "dependencies": ["control_agent"],
        "io_schema": {
            "input": {"type": "object", "properties": {"requirement": {"type": "string"}, "schema": {"type": "object"}}},
            "output": {"type": "object", "properties": {"content": {"type": "string"}, "sections": {"type": "array"}, "rationale": {"type": "string"}}},
            "consumes": ["improvement_decisions"],
            "produces": ["generated_prompt"]
        },
        "prompt": PROMPT_ENGINEER_SYSTEM_PROMPT
    },
    {
        "name": "tool_builder",
        "capabilities": ["generate_code", "create_tests", "validate_safety"],
        "dependencies": ["control_agent"],
        "io_schema": {
            "input": {"type": "object", "properties": {"specification": {"type": "object"}}},
            "output": {"type": "object", "properties": {"code": {"type": "string"}, "test_cases": {"type": "array"}, "imports": {"type": "array"}}},
            "consumes": ["improvement_decisions"],
            "produces": ["generated_skill"]
        },
        "prompt": TOOL_BUILDER_SYSTEM_PROMPT
    },
    {
        "name": "quality_judge",
        "capabilities": ["evaluate_quality", "compare_outputs", "score_improvements"],
        "dependencies": [],
        "io_schema": {
            "input": {"type": "object", "properties": {"output_a": {"type": "object"}, "output_b": {"type": "object"}, "criteria": {"type": "array"}}},
            "output": {"type": "object", "properties": {"winner": {"type": "string"}, "score_a": {"type": "number"}, "score_b": {"type": "number"}, "rationale": {"type": "string"}}},
            "consumes": ["ab_test_samples"],
            "produces": ["quality_judgment"]
        },
        "prompt": QUALITY_JUDGE_SYSTEM_PROMPT
    },
    {
        "name": "execution_analyzer",
        "capabilities": ["analyze_telemetry", "detect_errors", "identify_bottlenecks"],
        "dependencies": [],
        "io_schema": {
            "input": {"type": "object", "properties": {"telemetry": {"type": "array"}}},
            "output": {"type": "object", "properties": {"findings": {"type": "array"}, "patterns": {"type": "array"}}},
            "consumes": ["execution_telemetry"],
            "produces": ["analysis_findings"]
        },
        "prompt": ANALYZER_SYSTEM_PROMPT
    }
]


async def get_db_session():
    """Create database session."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


async def create_agent_with_prompt(session: AsyncSession, agent_data: dict, team: str) -> tuple[str, str]:
    """Create an agent and its prompt in the database."""
    # Check if agent already exists
    result = await session.execute(
        select(Agent).where(Agent.name == agent_data["name"])
    )
    existing = result.scalar_one_or_none()
    if existing:
        # Update prompt content and io_schema if changed
        if existing.prompt_id:
            prompt_result = await session.execute(
                select(Prompt).where(Prompt.id == existing.prompt_id)
            )
            existing_prompt = prompt_result.scalar_one_or_none()
            if existing_prompt and existing_prompt.content != agent_data["prompt"]:
                existing_prompt.content = agent_data["prompt"]
                logger.info(f"  Updated prompt for {agent_data['name']}")
        if existing.io_schema != agent_data["io_schema"]:
            existing.io_schema = agent_data["io_schema"]
            logger.info(f"  Updated io_schema for {agent_data['name']}")
        await session.commit()
        logger.info(f"  Synced {agent_data['name']} (already exists)")
        return existing.id, "skipped"

    # Create prompt first
    prompt_id = str(uuid4())
    prompt = Prompt(
        id=prompt_id,
        name=f"{agent_data['name']}_prompt",
        content=agent_data["prompt"],
        prompt_metadata={"team": team, "agent": agent_data["name"]},
        is_active=True
    )
    session.add(prompt)

    # Create agent
    agent_id = str(uuid4())
    agent = Agent(
        id=agent_id,
        name=agent_data["name"],
        dependencies=agent_data["dependencies"],
        io_schema=agent_data["io_schema"],
        prompt_id=prompt_id,
        is_active=True,
        agent_metadata={"team": team}
    )
    session.add(agent)

    await session.commit()
    logger.info(f"  Created {agent_data['name']} ({agent_id[:8]}...)")
    return agent_id, "created"


async def seed_agents():
    """Seed all agents into the database."""
    logger.info("=" * 50)
    logger.info("Seeding Lumari Agents")
    logger.info("=" * 50)

    async for session in get_db_session():
        # Seed Main Team
        logger.info("\n[Main Team] Report Generation Pipeline:")
        main_created = 0
        main_skipped = 0
        for agent_data in MAIN_TEAM_AGENTS:
            _, status = await create_agent_with_prompt(session, agent_data, "main_team")
            if status == "created":
                main_created += 1
            else:
                main_skipped += 1

        # Seed Developer Team
        logger.info("\n[Developer Team] Self-Improvement Pipeline:")
        dev_created = 0
        dev_skipped = 0
        for agent_data in DEVELOPER_TEAM_AGENTS:
            _, status = await create_agent_with_prompt(session, agent_data, "developer_team")
            if status == "created":
                dev_created += 1
            else:
                dev_skipped += 1

        # Summary
        logger.info("\n" + "=" * 50)
        logger.info("Seeding Complete!")
        logger.info(f"Main Team:      {main_created} created, {main_skipped} skipped")
        logger.info(f"Developer Team: {dev_created} created, {dev_skipped} skipped")
        logger.info(f"Total Agents:   {main_created + dev_created + main_skipped + dev_skipped}")
        logger.info("=" * 50)


async def show_status():
    """Show current agent status."""
    async for session in get_db_session():
        result = await session.execute(select(Agent))
        agents = result.scalars().all()

        logger.info("\n" + "=" * 50)
        logger.info("Current Agents in Database")
        logger.info("=" * 50)

        if not agents:
            logger.info("No agents found. Run: python scripts/seed_agents.py")
            return

        # Group by team
        main_team = []
        dev_team = []
        other = []

        for agent in agents:
            metadata = agent.agent_metadata or {}
            team = metadata.get("team", "unknown")
            if team == "main_team":
                main_team.append(agent)
            elif team == "developer_team":
                dev_team.append(agent)
            else:
                other.append(agent)

        if main_team:
            logger.info("\n[Main Team]")
            for a in main_team:
                status = "active" if a.is_active else "inactive"
                logger.info(f"  - {a.name} ({status})")

        if dev_team:
            logger.info("\n[Developer Team]")
            for a in dev_team:
                status = "active" if a.is_active else "inactive"
                logger.info(f"  - {a.name} ({status})")

        if other:
            logger.info("\n[Other/Legacy]")
            for a in other:
                status = "active" if a.is_active else "inactive"
                logger.info(f"  - {a.name} ({status})")

        logger.info(f"\nTotal: {len(agents)} agents")


async def reset_and_seed():
    """Delete all agents and re-seed."""
    logger.info("Resetting agents...")

    async for session in get_db_session():
        # Delete all agents and prompts
        await session.execute(delete(Agent))
        await session.execute(delete(Prompt))
        await session.commit()
        logger.info("Deleted all existing agents and prompts")

    # Re-seed
    await seed_agents()


def main():
    parser = argparse.ArgumentParser(description="Seed Lumari agents")
    parser.add_argument("--status", action="store_true", help="Show current agents")
    parser.add_argument("--reset", action="store_true", help="Delete all and re-seed")

    args = parser.parse_args()

    if args.status:
        asyncio.run(show_status())
    elif args.reset:
        asyncio.run(reset_and_seed())
    else:
        asyncio.run(seed_agents())


if __name__ == "__main__":
    main()
