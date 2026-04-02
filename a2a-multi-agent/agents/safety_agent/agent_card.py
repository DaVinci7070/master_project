
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a_common.config import SAFETY_URL


SAFETY_SKILL = AgentSkill(
    id="analyze_construction_safety",
    name="Analysiert Sicherheitsvorfälle auf Baustellen",
    description=(
        "Extrahiert und klassifiziert Sicherheitsvorfälle aus Baustellentranskripten. "
        "Erkennt Unfälle, Beinahe-Unfälle, Gefahren und PSA-Verstöße. "
        "Bewertet den Compliance-Status nach deutschen Arbeitsschutzvorschriften."
    ),
    tags=[
        "safety",
        "hse",
        "construction",
        "accident",
        "hazard",
        "ppe",
        "sicherheit",
        "arbeitsschutz",
        "baustelle",
    ],
    examples=[
        "Analysiere das Transkript auf Arbeitsunfälle und Sicherheitsverstöße.",
        "Identifiziere alle PSA-Verstöße und fehlende Schutzausrüstung.",
        "Bewerte die Sicherheitslage auf der Baustelle basierend auf dem Protokoll.",
    ],
)


PUBLIC_AGENT_CARD = AgentCard(
    name="Safety Agent",
    description=(
        "Spezialisierter Agent zur Analyse von Arbeitssicherheit auf Baustellen. "
        "Identifiziert Unfälle, Gefahren, PSA-Verstöße und bewertet den "
        "Compliance-Status nach HSE-Standards."
    ),
    url=os.getenv("SAFETY_PUBLIC_URL", SAFETY_URL),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,
    ),
    skills=[SAFETY_SKILL],
    supports_authenticated_extended_card=False,
)
