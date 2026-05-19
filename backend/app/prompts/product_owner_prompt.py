"""Product Owner System Prompt — geladen aus config/agents/product_owner.yaml"""
from app.agents.agent_definitions import get_agent_prompt

PRODUCT_OWNER_SYSTEM_PROMPT = get_agent_prompt("product_owner")
