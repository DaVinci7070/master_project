"""Execution Analyzer System Prompt — geladen aus config/agents/execution_analyzer.yaml"""
from app.agents.agent_definitions import get_agent_prompt

ANALYZER_SYSTEM_PROMPT = get_agent_prompt("execution_analyzer")
