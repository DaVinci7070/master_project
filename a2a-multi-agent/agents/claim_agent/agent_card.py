
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a_common.config import CLAIM_URL


CLAIM_SKILL = AgentSkill(
    id="analyze_construction_claims",
    name="Analysiert Nachträge und Claims aus Transkripten",
    description=(
        "Extrahiert und klassifiziert potenzielle Nachträge, Regiearbeiten und "
        "Planänderungen aus Baustellentranskripten. Erkennt zusätzliche Leistungen "
        "außerhalb des Leistungsverzeichnisses."
    ),
    tags=[
        "claim",
        "nachtrag",
        "regie",
        "construction",
        "mehrkosten",
        "zusatzleistung",
        "baustelle",
    ],
    examples=[
        "Analysiere das Transkript auf potenzielle Nachträge und Zusatzleistungen.",
        "Extrahiere alle erwähnten Regiearbeiten und Planänderungen.",
        "Identifiziere Arbeiten die nicht im Leistungsverzeichnis enthalten sind.",
    ],
)


PUBLIC_AGENT_CARD = AgentCard(
    name="Claim Agent",
    description=(
        "Spezialisierter Agent zur Extraktion und Analyse von Nachträgen, "
        "Regiearbeiten und Planänderungen aus Baustellentranskripten. "
        "Identifiziert potenzielle Mehrkosten-Sachverhalte."
    ),
    url=os.getenv("CLAIM_PUBLIC_URL", CLAIM_URL),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,
    ),
    skills=[CLAIM_SKILL],
    supports_authenticated_extended_card=False,
)
