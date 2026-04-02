
from __future__ import annotations

from typing import List, Literal
from pydantic import BaseModel, Field


class ClaimItem(BaseModel):

    
    topic: str = Field(
        ...,
        description="Thema/Art des Nachtrags (z.B. 'Zusätzliche Abdichtungsarbeiten', 'Planänderung Fenster')"
    )
    justification: str = Field(
        ...,
        description="Begründung warum dies ein Nachtrag ist (z.B. 'Nicht im LV enthalten', 'Nachträgliche Kundenanforderung')"
    )
    estimated_impact: str = Field(
        ...,
        description="Geschätzte Auswirkung (z.B. 'ca. 2.500 EUR Mehrkosten', '3 Tage Verzögerung', 'Noch zu kalkulieren')"
    )
    claim_type: Literal["Nachtrag", "Regiearbeit", "Planänderung", "Sonstiges"] = Field(
        default="Nachtrag",
        description="Typ des Claims: Nachtrag, Regiearbeit, Planänderung oder Sonstiges"
    )


class PotentialClaims(BaseModel):

    
    claims: List[ClaimItem] = Field(
        default_factory=list,
        description="Liste der gefundenen Claims/Nachträge"
    )
    
    @property
    def total_count(self) -> int:
        """Gesamtzahl der Claims."""
        return len(self.claims)
    
    @property
    def nachtrag_count(self) -> int:

        return sum(1 for item in self.claims if item.claim_type == "Nachtrag")
    
    @property
    def regie_count(self) -> int:

        return sum(1 for item in self.claims if item.claim_type == "Regiearbeit")


class ClaimAnalysisResult(BaseModel):

    
    claims: PotentialClaims = Field(default_factory=PotentialClaims)
    summary: str = Field(
        default="",
        description="Kurze Zusammenfassung der Claim-Situation"
    )
