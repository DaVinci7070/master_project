
from pydantic import BaseModel, Field
from typing import List, Any


class ClaimItemSchema(BaseModel):
    
    topic: str = Field(..., description="Thema/Art des Nachtrags")
    justification: str = Field(..., description="Begründung")
    estimated_impact: str = Field(..., description="Geschätzte Auswirkung")
    claim_type: str = Field(..., description="Typ des Claims")


class ClaimInput(BaseModel):
    
    transcript: str = Field(
        ..., description="Transkript zur Claim-Analyse"
    )


class ClaimResult(BaseModel):
    
    claims: List[Any] = Field(
        default_factory=list,
        description="Liste der extrahierten Claims"
    )
    total_count: int = Field(
        default=0,
        description="Gesamtzahl der Claims"
    )
    nachtrag_count: int = Field(
        default=0,
        description="Anzahl der Nachträge"
    )
    summary: str = Field(
        default="",
        description="Zusammenfassung der Claim-Situation"
    )


class ClaimOutput(BaseModel):
    
    claim_result: ClaimResult = Field(
        ..., description="Das strukturierte Claim-Ergebnis"
    )
