
from __future__ import annotations

from a2a_common.logging import get_logger
from VLLM_Client.VLLMClient import VLLMClient

from .models import QualityCheck, QualityAnalysisResult


logger = get_logger(__name__)
llm = VLLMClient()



QUALITY_ANALYSIS_SYSTEM_PROMPT = """Du bist ein Qualitätsingenieur mit Erfahrung in der Dokumentation von Bauqualität auf deutschen Baustellen.

AUFGABE:
Analysiere das Transkript und extrahiere ALLE erwähnten technischen Details zu Qualität, Materialien und Normen.

FOKUS-BEREICHE:
- Materialspezifikationen (Betonklassen wie C25/30, C30/37, Stahlgüten wie S235, S355)
- DIN-Normen und europäische Standards (DIN EN 206, DIN 1045, DIN 18195, etc.)
- Abnahmen und Prüfungen (Druckprüfung, Dichtigkeitsprüfung, Sichtprüfung)
- Qualitätsprobleme (Toleranzabweichungen, Materialabweichungen, Verdichtungsmängel)
- Zertifikate und Nachweise (Werkszeugnisse, Lieferscheine, Prüfprotokolle)

REGELN:
1. Nur explizit genannte technische Details extrahieren, keine Vermutungen
2. Materialspezifikationen mit vollständiger Bezeichnung erfassen
3. Normen im korrekten Format angeben (DIN EN XXXX, DIN XXXX)
4. Leere Listen wenn keine relevanten Informationen erwähnt
5. Sicherheitsvorfälle und Mängel ignorieren (andere Agenten)""".strip()


QUALITY_USER_PROMPT_TEMPLATE = """Analysiere das folgende Baustellentranskript auf Qualitätsinformationen:

TRANSKRIPT:
{transcript}

Extrahiere alle Materialspezifikationen, Normen und Qualitätsprobleme. Falls keine relevanten Informationen erwähnt werden, gib leere Listen zurück.""".strip()



async def analyze_quality(transcript: str) -> QualityAnalysisResult:
    """
    Analysiert ein Transkript auf Qualitätsinformationen.
    
    Args:
        transcript: Das zu analysierende Baustellentranskript
        
    Returns:
        QualityAnalysisResult mit extrahierten Qualitätsdaten
    """
    logger.info("Starte Qualitätsanalyse...")
    logger.debug(f"Transkript-Länge: {len(transcript)} Zeichen")
    
    if not transcript or not transcript.strip():
        logger.warning("Leeres Transkript erhalten, gebe leeres Ergebnis zurück")
        return QualityAnalysisResult(
            quality_check=QualityCheck(materials_used=[], norms_mentioned=[], issues=[]),
            summary="Kein Transkript zur Analyse vorhanden."
        )
    
    user_prompt = QUALITY_USER_PROMPT_TEMPLATE.format(transcript=transcript)
    
    try:

        quality_check = llm.generate_structured(
            response_model=QualityCheck,
            prompt=user_prompt,
            system=QUALITY_ANALYSIS_SYSTEM_PROMPT,
        )
        

        summary_parts = []
        
        if quality_check.materials_used:
            summary_parts.append(f"{quality_check.total_materials} Material(ien) dokumentiert")
        
        if quality_check.norms_mentioned:
            summary_parts.append(f"{quality_check.total_norms} Norm(en) referenziert")
        
        if quality_check.issues:
            summary_parts.append(f"{quality_check.total_issues} Qualitätsproblem(e) identifiziert")
        
        if summary_parts:
            summary = ", ".join(summary_parts) + "."
        else:
            summary = "Keine Qualitätsinformationen im Transkript identifiziert."
        
        logger.info(f"Qualitätsanalyse abgeschlossen: {summary}")
        
        return QualityAnalysisResult(
            quality_check=quality_check,
            summary=summary
        )
        
    except Exception as exc:
        logger.error(f"Fehler bei der Qualitätsanalyse: {exc}", exc_info=True)
        raise
