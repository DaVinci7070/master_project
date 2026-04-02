
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a_common.config import TEMPLATE_URL  

TEMPLATE_SKILL = AgentSkill(
    id="select_template_for_payload",
    name="Wählt ein passendes Berichtstemplate",
    description=(
        "Wählt anhand der Nutzereingaben (z.B. user_id, domain, user_profile, "
        "Inhalt des Transkripts) ein geeignetes Berichtstemplate aus. "
        "Nutzt dazu MCP-Tools und Qdrant, um Templates semantisch zu finden."
    ),
    tags=[
        "templates",
        "selection",
        "retrieval",
        "qdrant",
        "mcp",
    ],
    examples=[
        "Finde das beste Template für einen deutschsprachigen Baustellen-Statusbericht.",
        "Wähle ein Berichtstemplate für domain='construction' und Rolle='projektleiter'.",
        "Gib mir das passende Template für dieses Meeting-Transkript.",
    ],
)

PUBLIC_AGENT_CARD = AgentCard(
    name="Template Selector Agent",
    description=(
        "Wählt auf Basis von User- und Kontextinformationen ein passendes "
        "Berichtstemplate aus (unter Verwendung von MCP und Qdrant)."
    ),
    url=os.getenv("TEMPLATE_PUBLIC_URL", TEMPLATE_URL),
    version="1.0.0",
    default_input_modes=["text"],   
    default_output_modes=["text"],  
    capabilities=AgentCapabilities(
        streaming=True,
    ),
    skills=[TEMPLATE_SKILL],
    supports_authenticated_extended_card=False,
)