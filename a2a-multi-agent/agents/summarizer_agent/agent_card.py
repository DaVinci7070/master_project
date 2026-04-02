
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a_common.config import SUMMARIZER_URL

SUMMARIZER_SKILL = AgentSkill(
    id="structured_report_summarization",
    name="Erzeugt strukturierte Berichte aus Transkripten und Kontext",
    description=(
        "Nimmt ein Transkript bzw. normalisierten Text und optionalen Kontext "
        "(z.B. RAG-Dokumente, Templates) entgegen und erzeugt daraus einen "
        "strukturierten, JSON-basierten Bericht."
    ),
    tags=[
        "summarization",
        "reports",
        "json-output",
        "templates",
    ],
    examples=[
        "Fasse dieses Transkript in einem strukturierten Bericht zusammen.",

    ],
)

PUBLIC_AGENT_CARD = AgentCard(
    name="Summarizer Agent",
    description=(
        "Erzeugt strukturierte, JSON-basierte Berichte aus Transkripten "
        "und optionalem Kontext (z.B. RAG-Dokumente, Templates)."
    ),
    url=os.getenv("SUMMARIZER_PUBLIC_URL", SUMMARIZER_URL),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,  
    ),
    skills=[SUMMARIZER_SKILL],
    supports_authenticated_extended_card=False,
)