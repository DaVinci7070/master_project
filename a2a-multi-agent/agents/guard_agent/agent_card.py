
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a_common.config import GUARD_URL  

GUARD_SKILL = AgentSkill(
    id="validate_report_guard",
    name="Prüft Berichte auf Halluzinationen und Konsistenz",
    description=(
        "Überprüft einen generierten Bericht auf inhaltliche Konsistenz mit "
        "dem ursprünglichen Transkript und optionalem RAG-Kontext. "
        "Korrigiert Stellen, die nicht belegt sind oder offensichtlich halluziniert sind"
    ),
    tags=[
        "guard",
        "validation",
        "consistency",
        "hallucination-check",
        "safety",
    ],
    examples=[
        "Prüfe, ob dieser Bericht nur Informationen enthält, die im Transkript vorkommen.",
        "Vergleiche diesen Report mit dem Transkript und dem RAG-Kontext und korrigiere ggf. erfundene Fakten.",
    ],
)

PUBLIC_AGENT_CARD = AgentCard(
    name="Guard Agent",
    description=(
        "Validiert generierte Berichte gegen das Original-Transkript und "
        "optionalen RAG-Kontext, um Halluzinationen und inkonsistente Aussagen zu erkennen."
    ),
    url=os.getenv("GUARD_PUBLIC_URL", GUARD_URL),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,
    ),
    skills=[GUARD_SKILL],
    supports_authenticated_extended_card=False,
)