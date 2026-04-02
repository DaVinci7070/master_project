# backend/question_agent/logic.py


from __future__ import annotations

import json
from typing import Tuple

from a2a_common.schemas.question import QuestionInput, QuestionOutput
from a2a_common.signals import (
    AgentSignal,
    create_suspend_signal,
    create_continue_signal,
    create_error_signal,
)
from a2a_common.logging import get_logger
from VLLM_Client.VLLMClient import VLLMClient

from .models import QuestionResult

logger = get_logger(__name__)
llm = VLLMClient()


QUESTION_PROMPT = """Du bist ein präziser Analyst für Berichte.
Deine Aufgabe: Prüfe, ob das TRANSKRIPT alle notwendigen Informationen enthält, die das TEMPLATE verlangt.

TRANSKRIPT:
{transcript}

TEMPLATE VORGABEN:
{template_json}

ANWEISUNG:
1. Analysiere das Transkript GRÜNDLICH. Suche auch nach impliziten Informationen oder Synonymen.
2. Prüfe für jedes definierte Feld, ob Informationen dazu im TRANSKRIPT enthalten sind.
3. Generiere Rückfragen NUR DANN, wenn ein im Template gefordertes Feld DEFINITIV FEHLT und für den Bericht ESSENZIELL ist.
4. Vermeide Redundanz: Wenn etwas im Text steht (auch nur angedeutet), frage NICHT danach.
5. Sollte kein Template beigelegt sein, analysiere das Ziel des Transkripts, was für ein Bericht es werden soll, und stelle dahingehend fragen, zu Informationen die essentiell für einen vollständigen Bericht sind und noch fehlen.
6. Stelle maximal 3 Fragen. Priorisiere fehlende Pflichtfelder (z.B. Ort, Zeit, Haupttätigkeit).

Antworte AUSSCHLIESSLICH als JSON:
{{
  "has_questions": true,
  "questions": [
    {{
      "id": "...",
      "question": "...",
      "field_name": "...",
      "kind": "text",
      "required": true
    }}
  ]
}}
"""


async def analyze(inputs: QuestionInput) -> Tuple[QuestionOutput, AgentSignal]:
  
    template_json = "{}"
    if inputs.template_result:
        template_json = json.dumps(inputs.template_result, ensure_ascii=False)
    

    prompt = QUESTION_PROMPT.format(
        transcript=inputs.transcript[:4000],
        template_json=template_json
    )
    
    try:

        llm_result: QuestionResult = llm.generate_structured(
            response_model=QuestionResult,
            prompt=prompt,
            temperature=0.1
        )
        

        output = QuestionOutput(
            question_result=llm_result.model_dump()
        )
        

        if llm_result.has_questions and llm_result.questions:

            signal = create_suspend_signal(
                data={
                    "questions": [q.model_dump() for q in llm_result.questions],
                    "has_questions": True
                },
                reason="MISSING_INFORMATION"
            )
            logger.info(f"Question Agent: SUSPEND - {len(llm_result.questions)} questions")
        else:

            signal = create_continue_signal()
            logger.info("Question Agent: CONTINUE - transcript complete")
        
        return output, signal
        
    except Exception as e:
        logger.error(f"Error in Question Agent analyze: {e}")
        

        return (
            QuestionOutput(question_result={}),
            create_error_signal(reason=str(e))
        )
