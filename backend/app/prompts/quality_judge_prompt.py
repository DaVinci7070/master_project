"""Quality Judge System Prompt — geladen aus config/agents/quality_judge.yaml"""
from app.agents.agent_definitions import get_agent_prompt

QUALITY_JUDGE_SYSTEM_PROMPT = get_agent_prompt("quality_judge")
