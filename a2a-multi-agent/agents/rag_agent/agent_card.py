
from __future__ import annotations

import os

from a2a.types import AgentCard, AgentCapabilities, AgentSkill

RAG_SKILL = AgentSkill(
    id="retrieve_rag_context",
    name="Retrieves report context via MCP",
    description=(
        "Ruft über den MCP-Server relevante, ähnliche Reports ab und erzeugt daraus "
        "einen komprimierten Kontext, der von nachfolgenden Agents"
        "verwendet werden kann. Der Agent discovered MCP-Tools dynamisch und entscheidet "
        "selbst, welche Tools er für den Use-Case aufruft."
    ),
    tags=[
        "rag",
        "retrieval",
        "reports",
        "context",
        "mcp",
        "tool-discovery",
        "compression",
    ],
    examples=[
        "Hole ähnliche Reports als Kontext für dieses Transkript.",
        "Erzeuge RAG-Kontext aus bestehenden Berichten für bessere Konsistenz.",
        "Nutze MCP-Tools, um passende Report-Historie zu finden und zu verdichten.",
    ],
)

PUBLIC_AGENT_CARD = AgentCard(
    name="RAG Agent",
    description=(
        "Erzeugt RAG-Kontext aus ähnlichen Reports (via MCP) zur Unterstützung "
        "nachfolgender Agents in der Pipeline."
    ),
    url=os.getenv("RAG_PUBLIC_URL", "http://rag:8004/"),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(
        streaming=True,
    ),
    skills=[RAG_SKILL],
    supports_authenticated_extended_card=False,
)