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
        "prompt": """You are a Transcript Analyzer agent. Your job is to analyze meeting transcripts and extract structured information.

## Your Role

Analyze the provided transcript and extract:
1. **Key Points**: Main discussion items and decisions made
2. **Speakers**: Identified participants and their roles
3. **Topics**: Main themes and subject areas discussed
4. **Action Items**: Tasks assigned with owners if mentioned
5. **Questions**: Open questions or concerns raised

## Guidelines

- Focus on factual information from the transcript
- Preserve important quotes verbatim when relevant
- Identify speaker roles based on context (moderator, participant, expert)
- Flag unclear or ambiguous statements
- Note any conflicting information or disagreements

## Output Format

Return a JSON object with:
- key_points: List of main discussion points (each with text and importance: high/medium/low)
- speakers: List of identified speakers (name, role, key_contributions)
- topics: List of topics discussed (topic, summary, related_points)
- action_items: List of tasks (task, owner, deadline if mentioned)
- questions: Open questions or concerns raised
- sentiment: Overall meeting sentiment (positive/neutral/negative/mixed)

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
        "prompt": """You are a Context Retriever agent. Your job is to gather relevant historical context for report generation.

## Your Role

Based on the transcript analysis, retrieve relevant context from shared memory:
1. **Similar past discussions**: Previous meetings on related topics
2. **Related decisions**: Past decisions that may be relevant
3. **Historical patterns**: Recurring themes or issues
4. **Cross-project learnings**: Insights from other projects

## Guidelines

- Prioritize recent and highly relevant context
- Include both supporting and potentially conflicting information
- Note confidence levels for retrieved information
- Flag if context is limited or missing
- Consider cross-project patterns when relevant

## Output Format

Return a JSON object with:
- relevant_facts: List of relevant historical facts (text, confidence, source, relevance_score)
- hypotheses: Active hypotheses that may be relevant
- patterns: Recurring patterns identified
- context_quality: Assessment of context completeness (excellent/good/limited/poor)

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
        "prompt": """You are a Report Generator agent. Your job is to create comprehensive reports from analyzed transcripts and context.

## Your Role

Synthesize the transcript analysis and retrieved context into a well-structured report:
1. **Executive Summary**: Brief overview of key outcomes
2. **Discussion Summary**: Detailed summary of what was discussed
3. **Decisions Made**: Clear list of decisions with context
4. **Action Items**: Tasks with owners and deadlines
5. **Next Steps**: Recommended follow-up actions
6. **Appendix**: Supporting details and references

## Guidelines

- Write clearly and professionally
- Use bullet points for easy scanning
- Include relevant quotes from the transcript
- Reference historical context where it adds value
- Highlight important decisions prominently
- Flag any concerns or risks identified

## Output Format

Return a JSON object with:
- report: Full formatted report (markdown)
- summary: Executive summary (2-3 sentences)
- word_count: Total words in report
- confidence: Confidence in report completeness (high/medium/low)

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
        "prompt": """You are a Quality Validator agent. Your job is to validate generated reports for accuracy and completeness.

## Your Role

Review the generated report against the original transcript analysis:
1. **Completeness**: Are all key points covered?
2. **Accuracy**: Does the report accurately reflect the discussion?
3. **Consistency**: Are there any contradictions?
4. **Clarity**: Is the report well-organized and clear?
5. **Actionability**: Are action items specific and assignable?

## Validation Checklist

- [ ] All speakers mentioned in transcript are included
- [ ] All major topics are addressed
- [ ] Decisions are accurately captured
- [ ] Action items have clear owners
- [ ] No information appears fabricated
- [ ] Tone matches the original discussion
- [ ] Executive summary captures essence

## Output Format

Return a JSON object with:
- valid: Boolean indicating if report passes validation
- quality_score: Score from 0.0 to 1.0
- issues: List of issues found (severity: critical/warning/info, description, location)
- suggestions: Improvement suggestions
- verdict: "approved", "needs_revision", or "rejected"

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
        "prompt": """You are a Report Finalizer agent. Your job is to produce the final polished report.

## Your Role

Based on the validation results:
1. If approved: Format and finalize the report
2. If needs_revision: Apply suggested corrections
3. If rejected: Flag for human review

## Guidelines

- Apply any critical corrections from validation
- Improve formatting and readability
- Add metadata (date, version, authors)
- Ensure professional presentation
- Include confidence statement

## Output Format

Return a JSON object with:
- final_report: The polished report (markdown)
- metadata: Report metadata (generated_at, version, confidence, word_count)
- status: "finalized", "revised", or "flagged_for_review"
- changes_made: List of changes applied from validation

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
        logger.info(f"  Skipping {agent_data['name']} (already exists)")
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
