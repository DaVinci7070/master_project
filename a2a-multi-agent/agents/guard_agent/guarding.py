# backend/guard_agent/guarding.py

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple, Optional
from pydantic import BaseModel, Field

from a2a_common.logging import get_logger
from VLLM_Client.VLLMClient import VLLMClient
from a2a_common.utils import safe_json_parse
from a2a.server.agent_execution import RequestContext
from a2a_common.utils import get_artifact_from_context

from .models import HallucinationIssue, GuardResult

logger = get_logger(__name__)
llm = VLLMClient()


CHECK_PROMPT_TEXT = """Du bist ein Qualitätsprüfer für automatisch generierte Berichte.

Deine Aufgabe:
1. Vergleiche den generierten Bericht mit dem Original-Transkript.
2. Nutze zusätzlich bereitgestellten Kontext (RAG), falls vorhanden.
3. Finde Aussagen im Bericht, die NICHT im Transkript oder Kontext belegt sind (Halluzinationen).
4. Finde faktische Fehler oder Widersprüche.
5. Ignoriere stilistische Änderungen und Umformulierungen – diese sind erlaubt.

Original-Transkript:
--------------------
{original_transcript}
--------------------

Generierter Bericht (Fließtext):
--------------------
{report_text}
--------------------

Zusätzlicher Kontext (RAG – diese Infos dürfen auch verwendet werden):
--------------------
{rag_context}
--------------------

Antwortformat (NUR valides JSON, keine Erklärungen):

{{
  "has_hallucinations": true/false,
  "issues": [
    {{
      "field": "Name des Abschnitts oder 'report'",
      "span": "Die problematische Textstelle aus dem Bericht",
      "reason": "Warum ist das eine Halluzination oder ein Fehler?",
      "correction": "Optionale, konkrete Korrektur der Stelle (oder null)"
    }}
  ]
}}

Falls keine Probleme gefunden: {{"has_hallucinations": false, "issues": []}}
"""

CORRECT_PROMPT_TEXT = """Du bist ein Korrektor für automatisch generierte Berichte.

Deine Aufgabe:
- Korrigiere den BERICHT anhand der identifizierten Probleme.
- Entferne oder korrigiere NUR die problematischen Stellen.
- Behalte alle korrekten Informationen und die Struktur des Berichts bei.
- Erfinde KEINE neuen Fakten, die nicht im Original-Transkript oder Kontext stehen.
- Wenn eine Aussage nicht belegbar ist, entferne sie oder formuliere sie neutraler.
- Antworte ausschließlich mit dem vollständig korrigierten Fließtext-Bericht.

Original-Transkript (Quelle der Wahrheit):
--------------------
{original_transcript}
--------------------

Aktueller Bericht (Fließtext):
--------------------
{report_text}
--------------------

Identifizierte Probleme:
--------------------
{issues_text}
--------------------

Antwortformat:
- NUR der korrigierte Bericht als Fließtext.
- KEIN JSON.
- KEINE Erklärungen.
"""

CHECK_PROMPT_JSON = """Du bist ein Qualitätsprüfer für strukturierte, JSON-basierte Berichte.

Deine Aufgabe:
1. Vergleiche den generierten JSON-Bericht mit dem Original-Transkript.
2. Nutze zusätzlich bereitgestellten Kontext (RAG), falls vorhanden.
3. Finde Werte/Fakten im JSON, die NICHT im Transkript oder Kontext belegt sind (Halluzinationen).
4. Finde faktische Fehler oder Widersprüche.
5. Ändere NICHT das Schema/Format – nur Werte bewerten.

Original-Transkript:
--------------------
{original_transcript}
--------------------

Generierter Bericht (JSON):
--------------------
{report_json}
--------------------

Zusätzlicher Kontext (RAG – diese Infos dürfen auch verwendet werden):
--------------------
{rag_context}
--------------------

Antwortformat (NUR valides JSON, keine Erklärungen):

{{
  "has_hallucinations": true/false,
  "issues": [
    {{
      "field": "JSON-Pfad, z.B. fields[3].value oder ort",
      "span": "Der problematische Wert (als String repräsentiert)",
      "reason": "Warum ist das eine Halluzination oder ein Fehler?",
      "correction": "Konkrekte Korrektur als String (oder null)"
    }}
  ]
}}

Falls keine Probleme gefunden: {{"has_hallucinations": false, "issues": []}}
"""

CORRECT_PROMPT_JSON = """Du bist ein Korrektor für strukturierte, JSON-basierte Berichte.

Deine Aufgabe:
- Korrigiere den JSON-Bericht anhand der identifizierten Probleme.
- Entferne oder korrigiere NUR problematische Werte.
- Behalte das JSON-Schema und die Struktur exakt bei (Keys/Arrays/Objekte dürfen nicht neu erfunden werden).
- Erfinde KEINE neuen Fakten, die nicht im Original-Transkript oder Kontext stehen.
- Wenn eine Aussage nicht belegbar ist, setze den Wert auf null/""/[] (passend zum Feldtyp) oder formuliere neutraler.

Original-Transkript (Quelle der Wahrheit):
--------------------
{original_transcript}
--------------------

Aktueller Bericht (JSON):
--------------------
{report_json}
--------------------

Identifizierte Probleme:
--------------------
{issues_text}
--------------------

Antwortformat:
- NUR valides JSON (derselbe Strukturtyp wie Input).
- KEINE Erklärungen.
"""

def format_rag_context(rag_items: List[Dict[str, Any]]) -> str:
    if not rag_items: return "(kein zusätzlicher Kontext)"
    parts: List[str] = []
    for item in rag_items:
        item_type = item.get("type", "unknown")
        title = item.get("title") or item.get("template_id") or ""
        text = item.get("text", "")
        parts.append(f"[{item_type}] {title}: {text[:500]}")
    return "\n".join(parts)

def format_issues(issues: List[HallucinationIssue]) -> str:
    if not issues: return "(keine)"
    lines: List[str] = []
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. Feld/Abschnitt: {issue.field}\n   Stelle/Wert: \"{issue.span}\"\n   Grund: {issue.reason}")
        if issue.correction is not None: lines.append(f"   Vorschlag: {issue.correction}")
    return "\n".join(lines)

def _try_parse_json_report(report: str) -> Tuple[bool, Optional[Any]]:
    if not isinstance(report, str): return False, None
    s = report.strip()
    if not s or not (s.startswith("{") or s.startswith("[")): return False, None
    try: return True, json.loads(s)
    except: return False, None

class HallucinationCheckResult(BaseModel):
    has_hallucinations: bool
    issues: List[HallucinationIssue] = Field(default_factory=list)

def _check_hallucinations_text(original_transcript: str, report_text: str, rag_context: List[Dict[str, Any]]) -> Tuple[bool, List[HallucinationIssue]]:
    rag_text = format_rag_context(rag_context)
    prompt = CHECK_PROMPT_TEXT.format(original_transcript=original_transcript[:4000], report_text=report_text[:4000], rag_context=rag_text[:2000])
    try:
        res = llm.generate_structured(
            response_model=HallucinationCheckResult,
            prompt=prompt, 
            temperature=0.1, 
            max_tokens=1024
        )
        return res.has_hallucinations, res.issues
    except Exception as e:
        logger.warning(f"Guard check failed: {e}")
        return False, []

def _correct_report_text(original_transcript: str, report_text: str, issues: List[HallucinationIssue]) -> str:
    prompt = CORRECT_PROMPT_TEXT.format(original_transcript=original_transcript[:4000], report_text=report_text[:4000], issues_text=format_issues(issues)[:2000])
    try:

        raw = llm.generate(prompt=prompt, temperature=0.1, max_tokens=1500, top_p=0.9).strip()
        return raw or report_text
    except: return report_text

def _check_hallucinations_json(original_transcript: str, report_obj: Any, rag_context: List[Dict[str, Any]]) -> Tuple[bool, List[HallucinationIssue]]:
    rag_text = format_rag_context(rag_context)
    prompt = CHECK_PROMPT_JSON.format(original_transcript=original_transcript[:4000], report_json=json.dumps(report_obj, ensure_ascii=False)[:6000], rag_context=rag_text[:2000])
    try:
        res = llm.generate_structured(
            response_model=HallucinationCheckResult,
            prompt=prompt, 
            temperature=0.1, 
            max_tokens=1024
        )
        return res.has_hallucinations, res.issues
    except: return False, []

def _correct_report_json(original_transcript: str, report_obj: Any, issues: List[HallucinationIssue]) -> str:
    prompt = CORRECT_PROMPT_JSON.format(original_transcript=original_transcript[:4000], report_json=json.dumps(report_obj, ensure_ascii=False)[:6000], issues_text=format_issues(issues)[:2000])
    try:
        corrected_dict = llm.generate_structured(
            response_model=Dict[str, Any],
            prompt=prompt,
            temperature=0.1, 
            max_tokens=2000
        )
        return json.dumps(corrected_dict, ensure_ascii=False)
    except Exception as e: 
        logger.warning(f"JSON correction failed: {e}")
        return json.dumps(report_obj, ensure_ascii=False)

async def guard_report(transcript: str, report: str, context_documents: List[Dict[str, Any]]) -> GuardResult:
    if not transcript.strip(): return GuardResult(has_hallucinations=False, issues=[], corrected_report=report)
    is_json, report_obj = _try_parse_json_report(report)
    if is_json and report_obj is not None:
        has_hallucinations, issues = _check_hallucinations_json(transcript, report_obj, context_documents)
        if not has_hallucinations or not issues: return GuardResult(has_hallucinations=False, issues=[], corrected_report=json.dumps(report_obj, ensure_ascii=False))
        corrected = _correct_report_json(transcript, report_obj, issues)
        return GuardResult(has_hallucinations=True, issues=issues, corrected_report=corrected)
    has_hallucinations, issues = _check_hallucinations_text(transcript, report, context_documents)
    if not has_hallucinations or not issues: return GuardResult(has_hallucinations=False, issues=[], corrected_report=report)
    corrected = _correct_report_text(transcript, report, issues)
    return GuardResult(has_hallucinations=True, issues=issues, corrected_report=corrected)