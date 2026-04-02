
from __future__ import annotations

from a2a_common.logging import get_logger
from VLLM_Client.VLLMClient import VLLMClient

from .models import SafetyReport, SafetyAnalysisResult


logger = get_logger(__name__)
llm = VLLMClient()



SAFETY_ANALYSIS_SYSTEM_PROMPT = """Du bist ein erfahrener Sicherheitsbeauftragter (SiFa) mit Spezialisierung auf Baustellensicherheit nach deutschen Arbeitsschutzvorschriften.

AUFGABE:
Analysiere das Transkript und identifiziere ALLE sicherheitsrelevanten Vorfälle und Beobachtungen.

FOKUS-BEREICHE:

1. UNFÄLLE (Type: "Accident")
   - Stürze von Leitern, Gerüsten, in Baugruben
   - Verletzungen durch Werkzeuge, Maschinen, herabfallende Gegenstände
   - Kollisionen mit Fahrzeugen oder Baugeräten
   - Eingeklemmte oder eingeschlossene Personen
   - Elektrounfälle, Verbrennungen

2. BEINAHE-UNFÄLLE (Type: "Near Miss")
   - Situationen, die fast zu einem Unfall geführt hätten
   - Abstürzende Gegenstände ohne Personenschaden
   - Ausweichmanöver bei Gefahrensituationen

3. GEFAHREN (Type: "Hazard")
   - Ungesicherte Baugruben, Öffnungen, Absturzkanten
   - Lose Kabel, stolpergelder Materialien
   - Defekte oder fehlende Absperrungen
   - Instabile Gerüste oder Leitern
   - Blockierte Fluchtwege
   - Unsichere Lagerung von Gefahrstoffen
   - Fehlende Kennzeichnung

4. PSA-VERSTÖSSE (psa_related: true)
   - Fehlende Schutzhelme
   - Fehlende Warnwesten/Signalkleidung
   - Fehlende Sicherheitsschuhe
   - Fehlende Handschuhe, Schutzbrillen, Gehörschutz
   - Beschädigte oder nicht geprüfte PSA

5. GERÜST-PROBLEME
   - Unvollständige Beläge oder Geländer
   - Nicht geprüfte Gerüste (fehlende Prüfplakette)
   - Überlastung, Beschädigungen

6. WETTERBEDINGUNGEN
   - Arbeiten bei Sturm, Gewitter, Eisglätte
   - Extreme Hitze ohne Schutzmaßnahmen

SCHWEREGRAD:
- Critical: Lebensgefahr, sofortiger Arbeitsstopp erforderlich
- High: Ernsthafte Verletzungsgefahr, sofortige Maßnahme nötig  
- Medium: Potenzielle Gefahr, zeitnahe Behebung erforderlich
- Low: Geringfügiger Verstoß, bei nächster Gelegenheit korrigieren

COMPLIANCE-STATUS (Gesamtbewertung):
- "compliant": Keine Verstöße, Sicherheit gewährleistet
- "minor_violations": Kleinere Verstöße, keine akute Gefahr
- "major_violations": Schwerwiegende Verstöße, dringender Handlungsbedarf
- "critical_violations": Kritische Verstöße, sofortiger Eingriff/Arbeitsstopp

REGELN:
1. Nur explizit genannte Vorfälle extrahieren, keine Vermutungen
2. Baumängel ignorieren (Defect Agent zuständig)
3. Bei Personen: Namen oder Funktionen erfassen wenn genannt
4. Leere Liste wenn keine Sicherheitsthemen erwähnt
5. Sei streng bei der Bewertung - Sicherheit hat höchste Priorität""".strip()


SAFETY_USER_PROMPT_TEMPLATE = """Analysiere das folgende Baustellentranskript auf Sicherheitsvorfälle und -verstöße:

TRANSKRIPT:
{transcript}

Identifiziere alle Unfälle, Beinahe-Unfälle, Gefahren und PSA-Verstöße. Bewerte den Gesamtstatus der Sicherheits-Compliance.""".strip()



async def analyze_safety(transcript: str) -> SafetyAnalysisResult:

    logger.info("Starte Sicherheitsanalyse...")
    logger.debug(f"Transkript-Länge: {len(transcript)} Zeichen")
    
    if not transcript or not transcript.strip():
        logger.warning("Leeres Transkript erhalten, gebe leeres Ergebnis zurück")
        return SafetyAnalysisResult(
            report=SafetyReport(incidents=[], compliance_status="compliant"),
            summary="Kein Transkript zur Analyse vorhanden."
        )
    
    user_prompt = SAFETY_USER_PROMPT_TEMPLATE.format(transcript=transcript)
    
    try:

        safety_report = llm.generate_structured(
            response_model=SafetyReport,
            prompt=user_prompt,
            system=SAFETY_ANALYSIS_SYSTEM_PROMPT,
        )
        

        if safety_report.incidents:
            incident_count = safety_report.incident_count
            critical_count = safety_report.critical_count
            accident_count = safety_report.accident_count
            
            summary_parts = [f"{incident_count} Sicherheitsvorfall/-vorfälle identifiziert"]
            
            if accident_count > 0:
                summary_parts.append(f"{accident_count} Unfall/Unfälle")
            if critical_count > 0:
                summary_parts.append(f"{critical_count} kritisch")
                
            summary_parts.append(f"Status: {safety_report.compliance_status}")
            summary = ", ".join(summary_parts) + "."
        else:
            summary = "Keine Sicherheitsvorfälle im Transkript identifiziert. Compliance-Status: compliant."
        
        logger.info(f"Sicherheitsanalyse abgeschlossen: {summary}")
        
        return SafetyAnalysisResult(
            report=safety_report,
            summary=summary
        )
        
    except Exception as exc:
        logger.error(f"Fehler bei der Sicherheitsanalyse: {exc}", exc_info=True)
        raise
