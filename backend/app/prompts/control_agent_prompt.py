"""Control Agent System Prompt — geladen aus config/agents/control_agent.yaml"""
from app.orchestration.agents.definitions import get_agent_prompt

CONTROL_AGENT_SYSTEM_PROMPT = get_agent_prompt("control_agent")
