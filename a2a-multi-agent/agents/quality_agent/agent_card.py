
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a_common.config import QUALITY_URL


QUALITY_SKILL = AgentSkill(
    id="analyze_construction_quality",
    name="Analysiert Qualitätsinformationen aus Transkripten",
    description=(
        "Extrahiert technische Qualitätsdaten aus Baustellentranskripten. "
        "Erkennt Materialspezifikationen, DIN-Normen, Prüfungen und Qualitätsprobleme. "
        "Dokumentiert Betonklassen, Stahlgüten und Abnahmeprotokolle."
    ),
    tags=[
        "quality",
        "construction",
        "materials",
        "norms",
        "DIN",
        "specifications",
        "baustelle",
        "qualität",
    ],
    examples=[
        "Analysiere das Transkript auf Materialspezifikationen und Normen.",
        "Extrahiere alle erwähnten Betonklassen und DIN-Normen.",
        "Identifiziere Qualitätsprobleme und fehlende Nachweise.",
    ],
)


PUBLIC_AGENT_CARD = AgentCard(
    name="Quality Agent",
    description=(
        "Spezialisierter Agent zur Extraktion von Qualitätsinformationen aus "
        "Baustellentranskripten. Dokumentiert Materialien, Normen und Prüfungen."
    ),
    url=os.getenv("QUALITY_PUBLIC_URL", QUALITY_URL),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,
    ),
    skills=[QUALITY_SKILL],
    supports_authenticated_extended_card=False,
)
