
from __future__ import annotations

from a2a_common.logging import get_logger
from VLLM_Client.VLLMClient import VLLMClient

from .models import DefectList, DefectEntry, DefectAnalysisResult


logger = get_logger(__name__)
llm = VLLMClient()



DEFECT_ANALYSIS_SYSTEM_PROMPT = """Du bist ein Baumängel-Experte mit Erfahrung in der Dokumentation von Baudefekten auf deutschen Baustellen.

AUFGABE:
Analysiere das Transkript und extrahiere ALLE erwähnten Baumängel. Für jeden Mangel erfasse: Ortsangabe (Geschoss, Raum, Bauteil), Beschreibung, Schweregrad und Handlungsbedarf.

FOKUS-BEREICHE:
- Risse und Strukturschäden (Haarrisse, Setzrisse, Fugenprobleme, Verformungen)
- Feuchtigkeit und Wasserschäden (Nässe, Schimmel, Durchfeuchtung, undichte Stellen)
- Materialdefekte (Abplatzungen, Korrosion, Rost, Verschleiß)
- Oberflächendefekte (Kratzer, Dellen, Farbabweichungen, Unebenheiten)
- Ausführungsfehler (falsche Maße, Toleranzabweichungen, mangelhafte Verarbeitung)

SCHWEREGRAD:
- Critical: Statische Gefährdung oder Sicherheitsrisiko, sofortige Maßnahmen erforderlich
- High: Sofortige Behebung nötig, kann weitere Schäden verursachen
- Medium: Behebung vor Abnahme erforderlich
- Low: Kosmetischer Mangel, keine funktionale Beeinträchtigung

REGELN:
1. Nur explizit genannte Mängel extrahieren, keine Vermutungen
2. Terminverzögerungen und Arbeitsunfälle ignorieren (andere Agenten)
3. Präzise Ortsangaben verwenden
4. Leere Liste wenn keine Mängel erwähnt""".strip()


DEFECT_USER_PROMPT_TEMPLATE = """Analysiere das folgende Baustellentranskript auf Baumängel:

TRANSKRIPT:
{transcript}

Extrahiere alle Mängel und klassifiziere nach Schweregrad. Falls keine Mängel erwähnt werden, gib eine leere Liste zurück.""".strip()



async def analyze_defects(transcript: str) -> DefectAnalysisResult:

    logger.info("Starte Mängelanalyse...")
    logger.debug(f"Transkript-Länge: {len(transcript)} Zeichen")
    
    if not transcript or not transcript.strip():
        logger.warning("Leeres Transkript erhalten, gebe leere Mängelliste zurück")
        return DefectAnalysisResult(
            defects=DefectList(items=[]),
            summary="Kein Transkript zur Analyse vorhanden."
        )
    
    user_prompt = DEFECT_USER_PROMPT_TEMPLATE.format(transcript=transcript)
    
    try:
        
        defect_list = llm.generate_structured(
            response_model=DefectList,
            prompt=user_prompt,
            system=DEFECT_ANALYSIS_SYSTEM_PROMPT,
        )
        
      
        if defect_list.items:
            critical_count = defect_list.critical_count
            high_count = defect_list.high_count
            total_count = defect_list.total_count
            
            summary_parts = [f"{total_count} Mängel identifiziert"]
            if critical_count > 0:
                summary_parts.append(f"{critical_count} kritisch")
            if high_count > 0:
                summary_parts.append(f"{high_count} hochpriorisiert")
            
            summary = ", ".join(summary_parts) + "."
        else:
            summary = "Keine Baumängel im Transkript identifiziert."
        
        logger.info(f"Mängelanalyse abgeschlossen: {summary}")
        
        return DefectAnalysisResult(
            defects=defect_list,
            summary=summary
        )
        
    except Exception as exc:
        logger.error(f"Fehler bei der Mängelanalyse: {exc}", exc_info=True)
        raise
