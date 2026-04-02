
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a_common.config import ORCHESTRATOR_URL

ORCHESTRATOR_SKILL = AgentSkill(
    id="orchestrate_report_pipeline",
    name="Orchestriert Agenten um ein Transkript in einen fertigen Bericht zu konvertieren",
    description=(
        "Nimmt ein Transkript oder freien Text entgegen und orchestriert "
        "interne A2A-Agenten, um einen konsistenten, validierten Bericht zu erzeugen."
    ),
    tags=[
        "orchestrator",
        "routing",
        "multistep",
        "reports",
    ],
    examples=[
        "Erzeuge einen Bericht aus diesem Meeting-Transkript.",
        "Ziehe relevante alte Reports per RAG hinzu, fasse zusammen "
        "und prüfe die Konsistenz.",
    ],
)

PUBLIC_AGENT_CARD = AgentCard(
    name="Orchestrator Agent",
    description=(
        "Koordiniert interne A2A-Agenten und bietet "
        "eine zentrale Schnittstelle für die Erstellung validierter Berichte."
    ),
    url=os.getenv("ORCHESTRATOR_PUBLIC_URL", ORCHESTRATOR_URL),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,  
    ),
    skills=[ORCHESTRATOR_SKILL],
    supports_authenticated_extended_card=False,
)

