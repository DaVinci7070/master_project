
from __future__ import annotations
import os
from a2a.types import AgentCard, AgentCapabilities, AgentSkill

QUESTION_URL = os.getenv("QUESTION_URL", "http://question:8007")

QUESTION_SKILL = AgentSkill(
    id="analyze_missing_information",
    name="Qualitätssicherung & Validierung",
    description=(
        "Führt eine QS-Analyse des Transkripts gegen das gewählte Template durch. "
        "Dies ist eine zwingende Voraussetzung für die Berichterstellung, um sicherzustellen, "
        "dass alle Pflichtfelder vorhanden sind und der Bericht vollständig ist. "
        "Erzeugt Rückfragen bei Unklarheiten."
    ),
    tags=[
        "validation",
        "quality-assurance",
        "completeness-check",
        "hitl",
        "prerequisite",
    ],
    examples=[
        "Führe eine Vollständigkeitsprüfung gegen das Template durch.",
        "Validierung: Fehlen Pflichtinformationen im Transkript?",
        "QS-Check: Ist das Transkript bereit für die Zusammenfassung?",
    ],
)

PUBLIC_AGENT_CARD = AgentCard(
    name="Question Agent (QS-Validator)",
    description=(
        "Essentieller Validierungs-Agent, der die Vollständigkeit des Transkripts sicherstellt "
        "und als Gatekeeper für die Berichterstellung fungiert."
    ),
    url=os.getenv("QUESTION_PUBLIC_URL", QUESTION_URL),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,
    ),
    skills=[QUESTION_SKILL],
    supports_authenticated_extended_card=False,
)
