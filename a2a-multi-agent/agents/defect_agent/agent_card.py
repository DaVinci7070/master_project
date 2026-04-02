
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a_common.config import DEFECT_URL


DEFECT_SKILL = AgentSkill(
    id="analyze_construction_defects",
    name="Analysiert Baumängel aus Transkripten",
    description=(
        "Extrahiert und klassifiziert Baumängel aus Baustellentranskripten. "
        "Erkennt Risse, Feuchtigkeitsschäden, Materialdefekte und Ausführungsfehler. "
        "Bewertet Schweregrad und Handlungsbedarf."
    ),
    tags=[
        "defect",
        "construction",
        "quality",
        "damage",
        "cracks",
        "moisture",
        "baustelle",
        "mängel",
    ],
    examples=[
        "Analysiere das Transkript auf Baumängel und klassifiziere deren Schweregrad.",
        "Extrahiere alle erwähnten Schäden, Risse und Feuchtigkeitsprobleme.",
        "Identifiziere kritische Mängel die sofortigen Handlungsbedarf erfordern.",
    ],
)


PUBLIC_AGENT_CARD = AgentCard(
    name="Defect Agent",
    description=(
        "Spezialisierter Agent zur Extraktion und Analyse von Baumängeln aus "
        "Baustellentranskripten. Klassifiziert Mängel nach Schweregrad und "
        "identifiziert Handlungsbedarf."
    ),
    url=os.getenv("DEFECT_PUBLIC_URL", DEFECT_URL),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,
    ),
    skills=[DEFECT_SKILL],
    supports_authenticated_extended_card=False,
)
