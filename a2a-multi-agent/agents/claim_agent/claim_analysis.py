
from __future__ import annotations

from a2a_common.logging import get_logger
from VLLM_Client.VLLMClient import VLLMClient

from .models import PotentialClaims, ClaimAnalysisResult


logger = get_logger(__name__)
llm = VLLMClient()



CLAIM_ANALYSIS_SYSTEM_PROMPT = """Du bist ein Experte für Bauvertragsrecht und Nachtragsmanagement auf deutschen Baustellen.

AUFGABE:
Analysiere das Transkript und identifiziere ALLE potenziellen Nachträge, Regiearbeiten und Planänderungen. Für jeden Claim erfasse: Thema, Begründung warum dies ein Nachtrag ist, und geschätzte Auswirkung.

FOKUS-BEREICHE:
- Nachträge: Zusätzliche Leistungen die NICHT im ursprünglichen Leistungsverzeichnis (LV) enthalten sind
- Regiearbeiten: Stundenweise abgerechnete Arbeiten (oft mit "Stundenlohn", "Regie", "nach Aufwand" gekennzeichnet)
- Planänderungen: Abweichungen vom ursprünglichen Bauplan oder der Ausschreibung
- Mehrkosten-Indikatoren: "Extra", "Zusatz", "nicht vorgesehen", "Änderungswunsch", "nachträglich beauftragt"

CLAIM-TYPEN:
- Nachtrag: Zusätzliche Leistung außerhalb des LV
- Regiearbeit: Stundenweise abgerechnete Arbeit
- Planänderung: Änderung gegenüber ursprünglichem Plan
- Sonstiges: Andere Mehrkosten-relevante Sachverhalte

SCHLÜSSELWÖRTER (auf diese achten):
- "Zusatzbeauftragung", "Zusatzleistung", "Extra-Arbeit"
- "Regie", "Stundenlohn", "nach Aufwand"
- "nicht im LV", "nicht vorgesehen", "nicht eingeplant"
- "Bauherr wünscht", "Änderung", "anders als geplant"
- "Mehrkosten", "Nachtrag", "zusätzlich beauftragen"

REGELN:
1. Nur explizit genannte Claims extrahieren, keine Vermutungen
2. Bei Unsicherheit ob es ein Claim ist: lieber aufnehmen zur Prüfung
3. Terminverzögerungen und Mängel ignorieren (andere Agenten)
4. Leere Liste wenn keine Claims erwähnt""".strip()


CLAIM_USER_PROMPT_TEMPLATE = """Analysiere das folgende Baustellentranskript auf potenzielle Nachträge, Regiearbeiten und Planänderungen:

TRANSKRIPT:
{transcript}

Extrahiere alle Claims und klassifiziere nach Typ. Falls keine Claims erwähnt werden, gib eine leere Liste zurück.""".strip()



async def analyze_claims(transcript: str) -> ClaimAnalysisResult:
   
    logger.info("Starte Claim-Analyse...")
    logger.debug(f"Transkript-Länge: {len(transcript)} Zeichen")
    
    if not transcript or not transcript.strip():
        logger.warning("Leeres Transkript erhalten, gebe leere Claims-Liste zurück")
        return ClaimAnalysisResult(
            claims=PotentialClaims(claims=[]),
            summary="Kein Transkript zur Analyse vorhanden."
        )
    
    user_prompt = CLAIM_USER_PROMPT_TEMPLATE.format(transcript=transcript)
    
    try:

        claims_list = llm.generate_structured(
            response_model=PotentialClaims,
            prompt=user_prompt,
            system=CLAIM_ANALYSIS_SYSTEM_PROMPT,
        )
        

        if claims_list.claims:
            nachtrag_count = claims_list.nachtrag_count
            regie_count = claims_list.regie_count
            total_count = claims_list.total_count
            
            summary_parts = [f"{total_count} potenzielle Claims identifiziert"]
            if nachtrag_count > 0:
                summary_parts.append(f"{nachtrag_count} Nachträge")
            if regie_count > 0:
                summary_parts.append(f"{regie_count} Regiearbeiten")
            
            summary = ", ".join(summary_parts) + "."
        else:
            summary = "Keine Claims im Transkript identifiziert."
        
        logger.info(f"Claim-Analyse abgeschlossen: {summary}")
        
        return ClaimAnalysisResult(
            claims=claims_list,
            summary=summary
        )
        
    except Exception as exc:
        logger.error(f"Fehler bei der Claim-Analyse: {exc}", exc_info=True)
        raise
