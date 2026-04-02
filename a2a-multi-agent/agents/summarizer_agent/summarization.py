# backend/summarizer_agent/summarization.py

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from a2a_common.logging import get_logger
from VLLM_Client.VLLMClient import VLLMClient  
from a2a_common.utils import safe_json_parse
from a2a.server.agent_execution import RequestContext
from a2a_common.utils import get_artifact_from_context, create_signal_response

logger = get_logger(__name__)

llm = VLLMClient()

def _get_template_from_result(template_result: dict | None) -> dict | None:
    if not template_result or not isinstance(template_result, dict):
        return None
    tpl = template_result.get("template") or template_result.get("content")
    return tpl if isinstance(tpl, dict) and tpl else None

def format_context_documents(context_documents: List[Dict[str, Any]]) -> str:
    if not context_documents:
        logger.warning("No context documents found")
        return "(kein zusätzlicher Kontext)"
    parts: List[str] = []
    for idx, item in enumerate(context_documents, start=1):
        item_type = item.get("source_tool") or item.get("type") or "RAG-Kontext"
        title = item.get("title") or item.get("template_id") or f"Dokument {idx}"
        text = item.get("text", "") or ""
        snippet = text[:800]
        parts.append(f"[{item_type}] {title}\n{snippet}")
    return "\n\n".join(parts)



FIELD_BASED_PROMPT = """
Du bist ein präziser Daten-Extraktor für Bauberichte.
Deine Aufgabe: Extrahiere Fakten für den Abschnitt "{heading}".

RELEVANTE FELDER:
{fields}

TRANSKRIPT:
{normalized_text}

VERFÜGBARE EXPERTEN-DATEN (Prio 1):
{specialized_data_text}

KONTEXT AUS FRÜHEREN BERICHTEN:
{context_text}

ANWEISUNGEN:
1. Prüfe zuerst die EXPERTEN-DATEN. Wenn dort bereits strukturierte Informationen (z.B. Mängellisten) vorliegen, übernimm diese Details.
2. Suche ergänzend im TRANSKRIPT nach Werten für die oben genannten Felder.
3. WICHTIG: Nutze den KONTEXT aus früheren Berichten als zusätzliche Informationsquelle. Wenn relevante Details vorhanden sind (z.B. frühere Vorfälle, bekannte Probleme), erwähne diese kurz.
4. Gib das Ergebnis als Markdown-Liste zurück.
5. Format: "- [Label]: [Wert]"
6. Sei extrem präzise bei Zahlen, Zeiten und Namen.
7. Wenn eine Info fehlt, schreibe nichts dazu.

Ergebnis für "{heading}":
""".strip()

FREE_TEXT_PROMPT = """
Du bist ein technischer Redakteur für das Bauwesen.
Deine Aufgabe: Verfasse einen Fließtext für den Abschnitt "{heading}".

BESCHREIBUNG: {description}

TRANSKRIPT:
{normalized_text}

VERFÜGBARE EXPERTEN-DATEN (Prio 1):
{specialized_data_text}

KONTEXT AUS FRÜHEREN BERICHTEN:
{context_text}

ANWEISUNGEN:
1. Schreibe einen professionellen, sachlichen Text basierend auf dem Transkript und den Experten-Daten.
2. Integriere die Experten-Daten (z.B. Mängeldetails, Sicherheitsvorfälle) nahtlos in den Text.
3. WICHTIG: Wenn der KONTEXT aus früheren Berichten relevante Informationen enthält (z.B. wiederkehrende Probleme, Bezüge zu früheren Vorfällen), integriere diese sinnvoll in den Text. Beispiel: "Ähnlich wie im Bericht von letzter Woche..." oder "Die bereits bekannten Probleme mit..."
4. Fasse zusammen, was zu diesem Thema gesagt wurde.
5. Nutze Fettdruck (**) für wichtige Details.
6. Schreibe direkt den Inhalt (ohne Überschrift).

Text für "{heading}":
""".strip()

CONTEXT_SUMMARY_PROMPT = """
Du bist ein Assistent, der Hintergrundinformationen für einen Baubericht zusammenfasst.
Deine Aufgabe: Fasse die wichtigsten Informationen aus den KONTEXT-DOKUMENTEN zusammen, die das aktuelle Transkript ergänzen oder in Kontext setzen.

AKTUELLES TRANSKRIPT:
{normalized_text}

FRÜHERE BERICHTE (KONTEXT):
{context_text}

ANWEISUNGEN:
1. Analysiere die FRÜHEREN BERICHTE und identifiziere relevante Informationen wie:
   - Wiederkehrende Probleme oder Baustellen
   - Frühere Vorfälle oder Mängel an ähnlichen Orten
   - Bekannte Personen oder Firmen
   - Historischer Kontext, der das aktuelle Transkript erklärt
2. Fasse diese Informationen in 2-4 prägnanten Sätzen zusammen.
3. Beginne mit "Aus früheren Berichten:" und liste die relevanten Punkte auf.
4. NUR wenn die früheren Berichte komplett unabhängig und nicht verwandt sind (andere Baustelle, andere Themen, keine Überschneidungen), antworte: "Keine relevanten Verbindungen zu früheren Berichten gefunden."

Zusammenfassung:
""".strip()

def _format_specialized_data(data: Dict[str, Any]) -> str:
    if not data:
        return "(Keine Experten-Daten verfügbar)"
    
    parts = []
    

    if "defect_list" in data:
        defects = data["defect_list"]

        items = defects.get("defects", []) if isinstance(defects, dict) else []
        if items:
            parts.append(f"MÄNGEL ({len(items)} gefunden):")
            for d in items:
                desc = d.get("description", "Keine Beschreibung")
                loc = d.get("location", "Unbekannt")
                sev = d.get("severity", "N/A")
                parts.append(f"- [{sev}] {loc}: {desc}")
    

    if "safety_report" in data:
        safety = data["safety_report"]
        incidents = safety.get("incidents", []) if isinstance(safety, dict) else []
        status = safety.get("compliance_status", "Unbekannt") if isinstance(safety, dict) else "Unbekannt"
        
        parts.append(f"SICHERHEIT (Status: {status}):")
        if incidents:
            for inc in incidents:
                itype = inc.get("type", "Vorfall")
                desc = inc.get("description", "")
                parts.append(f"- {itype}: {desc}")
                
    # 3. Claim Report
    if "claim_report" in data:
        claims = data["claim_report"]
        c_items = claims.get("claims", []) if isinstance(claims, dict) else []
        if c_items:
            parts.append(f"NACHTRÄGE ({len(c_items)}):")
            for c in c_items:
                topic = c.get("topic", "")
                est = c.get("estimated_impact", "")
                parts.append(f"- {topic} (Impact: {est})")
                

    if "quality_report" in data:
        quality = data["quality_report"]
        issues = quality.get("issues", []) if isinstance(quality, dict) else []
        norms = quality.get("norms_mentioned", []) if isinstance(quality, dict) else []
        
        if issues or norms:
            parts.append("QUALITÄT:")
            if norms:
                parts.append(f"- Normen: {', '.join(norms)}")
            if issues:
                parts.append("- Probleme:")
                for i in issues:
                    parts.append(f"  * {i}")

    if not parts:
        return "(Daten leer)"
        
    return "\n".join(parts)


async def summarize_report(
    transcript: str,
    context_documents: Optional[List[Dict[str, Any]]] = None,
    template_result: Optional[Dict[str, Any]] = None,
    specialized_data: Optional[Dict[str, Any]] = None,
) -> str:
    context_documents = context_documents or []
    specialized_data = specialized_data or {}

    if not transcript or not transcript.strip():
        logger.warning("Summarizer: Leeres Transkript.")
        return ""

    logger.info(f"Summarizer: Processing with {len(context_documents)} context documents")
    if context_documents:
        logger.info(f"Summarizer: First context doc keys: {list(context_documents[0].keys())}")

    context_text = format_context_documents(context_documents)
    logger.info(f"Summarizer: Formatted context_text length: {len(context_text)} chars")
    specialized_data_text = _format_specialized_data(specialized_data)
    
    normalized_text = transcript.strip()[:6000]

    template: Optional[Dict[str, Any]] = None
    template_id: Optional[str] = None
    

    if template_result and isinstance(template_result, dict):
        template_id = template_result.get("template_id")
        tpl = _get_template_from_result(template_result)
        if tpl:
            template = tpl


    
    result_parts = []
    
    if template and "structure" in template and "sections" in template["structure"]:
        logger.info("Summarizer: Task Decomposition Mode (id=%s)", template_id)
        

        title = template.get("name", "Baubericht")
        result_parts.append(f"# {title}\n")
        
        sections = template["structure"]["sections"]
        for section in sections:
            heading = section.get("heading", "Abschnitt")
            logger.info("... processing section: %s", heading)
            
            sec_content = await _process_section(
                section, 
                normalized_text, 
                context_text, 
                specialized_data_text
            )
            
            result_parts.append(f"## {heading}")
            result_parts.append(sec_content)
            result_parts.append("\n") # Spacer
            
    else:

        logger.warning("Summarizer: No template structure found. Cannot generate report.")
        result_parts.append("Fehler: Kein gültiges Template mit Struktur gefunden.")


    result_parts.append("\n## Relevanter Kontext")
    if context_documents:
        context_summary = await _generate_context_summary(normalized_text, context_text)
        result_parts.append(context_summary)
    else:
        result_parts.append("Kein zusätzlicher Kontext verwendet.")

    return "\n".join(result_parts)

async def _generate_context_summary(transcript: str, context: str) -> str:
    if not context or not context.strip():
        return "Kein Kontext verfügbar."
        
    prompt = CONTEXT_SUMMARY_PROMPT.format(
        normalized_text=transcript,
        context_text=context
    )
    
    try:
        summary = llm.generate(prompt=prompt, temperature=0.1, max_tokens=300).strip()
        return summary
    except Exception as e:
        logger.error(f"Error generating context summary: {e}")
        return "Zusammenfassung des Kontexts konnte nicht erstellt werden."

async def _process_section(
    section_def: Dict[str, Any], 
    transcript: str, 
    context: str,
    specialized_data_text: str
) -> str:
    heading = section_def.get("heading", "")
    description = section_def.get("description", "")
    

    prompt = ""
    
    if "fields" in section_def and section_def["fields"]:
        # Field Extraction Mode
        fields = section_def["fields"]
        fields_list = [f"- {f.get('label', f.get('key'))}: {f.get('description', '')}" for f in fields]
        fields_str = "\n".join(fields_list)
        
        prompt = FIELD_BASED_PROMPT.format(
            heading=heading,
            fields=fields_str,
            normalized_text=transcript,
            context_text=context,
            specialized_data_text=specialized_data_text
        )
    else:

        prompt = FREE_TEXT_PROMPT.format(
            heading=heading,
            description=description,
            normalized_text=transcript,
            context_text=context,
            specialized_data_text=specialized_data_text
        )
    
    try:

        content = llm.generate(prompt=prompt, temperature=0.1, max_tokens=600).strip()
        return content
    except Exception as e:
        logger.error(f"Error generating section {heading}: {e}")
        return "(Fehler bei der Generierung dieses Abschnitts)"
