# backend/orchestrator_agent/executor.py


from __future__ import annotations

import json
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from a2a_common.agent_registry import AgentRegistry
from a2a_common.remote_agent import RemoteAgent
from a2a_common.utils import get_input_envelope_and_text_from_context
from a2a_common.logging import get_logger

from .config import get_registry_path
from .artifacts import OrchestrationState, OrchestrationStatus
from .planning import OrchestrationPlanner
from .persistence import load_state
from VLLM_Client.VLLMClient import VLLMClient


logger = get_logger(__name__)


class ReportMetadata(BaseModel):

    title: str
    tags: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    time: Optional[str] = None


class OrchestratorAgentExecutor(AgentExecutor):

    def __init__(self) -> None:
        super().__init__()

        logger.info("Initializing OrchestratorAgentExecutor")

        registry_path = get_registry_path()
        logger.info("Lade Agent-Registry von %s", registry_path)
        self.registry = AgentRegistry(str(registry_path))

        self.remote_agents: Dict[str, RemoteAgent] = self._build_remote_agents()

        self.llm_client = VLLMClient()

        self.planner = OrchestrationPlanner(
            llm=self.llm_client,
            registry=self.registry,
            remote_agents=self.remote_agents,
        )

    def _build_remote_agents(self) -> Dict[str, RemoteAgent]:
        logger.info("Build Remote agent Dictionary")
        agent_database = self.registry.getAllAgents()
        remote_agents: Dict[str, RemoteAgent] = {}

        for agent_entry in agent_database.values():
            logger.info("Registrierter Agent: %s -> %s", agent_entry.key, agent_entry.url)
            remote_agents[agent_entry.key] = RemoteAgent(agent_entry.url, agent_id=agent_entry.key)

        logger.info(f"Remote Agent Dict: \n {remote_agents}")
        return remote_agents

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            logger.info("Starte Orchestrator-Ausführung.")

            envelope, transcript = get_input_envelope_and_text_from_context(context)
            
            logger.info(f"DEBUG: Envelope Keys: {list(envelope.keys()) if envelope else 'None'}")
            logger.info(f"DEBUG: Transcript Length: {len(transcript) if transcript else 0}")

            state: OrchestrationState | None = None


            if envelope and "run_id" in envelope:
                run_id = envelope["run_id"]
                logger.info("Versuche OrchestrationState für run_id=%s zu laden.", run_id)
                existing_state = await load_state(run_id)
                if existing_state:
                    state = existing_state
                    
                    if "answers" in envelope and envelope["answers"]:
                        logger.info("Antworten für HITL erhalten. Speichere als Artifact 'user_answers'.")
                        state.set_artifact("user_answers", envelope["answers"], kind="json")
                    
                    if "answer_transcript" in envelope and envelope["answer_transcript"]:
                        ans_ts = envelope["answer_transcript"]
                        logger.info("Zusätzliches Antwort-Transkript erhalten. Merge mit Original-Transkript.")
                        
                        old_ts = ""
                        if state.has_artifact("original_transcript"):
                            old_ts = str(state.get_value("original_transcript"))
                        
                        new_ts = f"{old_ts}\n\n[USER CLARIFICATION]\n{ans_ts}"
                        state.set_artifact("original_transcript", new_ts, kind="text")

                    state.current_step_idx += 1
                    state.status = OrchestrationStatus.PENDING
                    logger.info(f"Resume: Proceeding to next step (idx={state.current_step_idx}). Status={state.status}")
                else:
                    logger.warning("Kein State für run_id=%s gefunden. Starte neu.", run_id)


            if not state:
                if not transcript:
                    logger.warning("Keine Eingabe im RequestContext gefunden (und kein gültiger Resume-State).")
                    await event_queue.enqueue_event(
                        new_agent_text_message("Ich habe keine Eingabe erhalten.")
                    )
                    return


                logger.info("Create OrchestrationState (New Run)")
                state = OrchestrationState(
                    original_transcript=transcript,
                    input_envelope=envelope or {},
                    goal="Erzeuge einen vollständigen und validierten Bericht aus dem Transkript."
                )
                state.set_artifact("original_transcript", transcript, kind="text")
                
                if envelope and "user_id" in envelope:
                    state.set_artifact("user_id", envelope["user_id"], kind="scalar")
                if envelope and "template_id" in envelope:
                    state.set_artifact("template_id", envelope["template_id"], kind="scalar")


            if envelope:
                state.set_artifact("last_input_envelope", envelope, kind="json")

                for key in ["user_id", "template_id", "user_profile"]:
                    if key in envelope:
                        state.set_artifact(
                            key, 
                            envelope[key], 
                            kind="json" if isinstance(envelope[key], (dict, list)) else "text"
                        )


            if not state.plan:
                plan_steps = self.planner.create_plan(state)
                state.plan = plan_steps
                state.status = OrchestrationStatus.PENDING
                logger.info(f"Neuer Plan erstellt mit {len(plan_steps)} Steps.")


            updated_state = await self.planner.run(state)



            if updated_state.status == OrchestrationStatus.WAITING_FOR_USER:
                logger.info("Sende HITL-Fragen an Client (run_id=%s).", updated_state.run_id)
                q_res = updated_state.get_value("question_result")
                response = {
                    "type": "orchestration_suspended",
                    "run_id": updated_state.run_id,
                    "status": str(updated_state.status),
                    "questions": q_res.get("questions", []) if isinstance(q_res, dict) else []
                }
                await event_queue.enqueue_event(new_agent_text_message(json.dumps(response, ensure_ascii=False)))
                return


            final_value = None
            for key in ["final_report", "summary_report"]:
                if updated_state.has_artifact(key):
                    final_value = updated_state.get_value(key)
                    break

            if final_value is None:
                logger.warning("Fallback case: No final value found for final report.")
                final_value = transcript

            if isinstance(final_value, (dict, list)):
                report_content_str = json.dumps(final_value, ensure_ascii=False, indent=2)
            else:
                report_content_str = str(final_value)


            logger.info("Generating Metadata (Title, Tags, Location, Time)...")
            
            template_title = "General Report"
            if updated_state.has_artifact("template_result"):
                tpl = updated_state.get_value("template_result")
                if isinstance(tpl, dict):
                    template_title = tpl.get("name") or tpl.get("title") or "Unknown Template"


            original_transcript_val = updated_state.get_value("original_transcript") or transcript or ""

            meta_prompt = f"""Du bist ein spezialisierter Assistent für die Datenextraktion aus Baustellenberichten.
Deine Aufgabe ist es, Metadaten (Titel, Tags, Ort, Zeit) aus dem Bericht und dem Transkript zu extrahieren.

INPUT DATEN:
- Template Name: {template_title}
- Original Transkript: {original_transcript_val[:2000]}...
- Generierter Bericht: {report_content_str[:4000]}

ANWEISUNGEN:
1. TITEL: Generiere einen kurzen, professionellen Titel (z.B. "Tagesbericht Baustelle X").
2. TAGS: Generiere exakt 3 relevante deutsche Tags.
3. LOCATION (Ort): 
   - Suche im Transkript UND Bericht nach Adressen, Städten oder Baustellenbezeichnungen.
   - Beispiel: "Baustelle Müllerstraße 5" -> "Müllerstraße 5"
   - Wenn nichts gefunden: null
4. TIME (Zeit):
   - Suche nach Uhrzeiten (14:00) oder Tageszeiten (Morgens, Vormittag).
   - Wenn nichts gefunden: null

Antworte strikt im JSON Format passend zum Schema.
"""
            try:
                meta_data_obj = self.llm_client.generate_structured(
                    response_model=ReportMetadata,
                    prompt=meta_prompt,
                    max_tokens=256
                )
                meta_data = meta_data_obj.model_dump()
            except Exception as e:
                logger.error(f"Metadata generation failed: {e}")
                meta_data = {
                    "title": "Generated Report",
                    "tags": ["report", "auto-generated", "ai"],
                    "location": None,
                    "time": None
                }


            if updated_state.has_artifact("template_result"):
                tpl = updated_state.get_value("template_result")
                if isinstance(tpl, dict):

                    tpl_meta = tpl.get("meta", {})
                    
                    if not meta_data.get("location") and tpl_meta.get("location"):
                        meta_data["location"] = tpl_meta.get("location")
                    

                    if not meta_data.get("location") and tpl.get("location"):
                        meta_data["location"] = tpl.get("location")


                    if not meta_data.get("time") and tpl_meta.get("date"):
                         meta_data["time"] = tpl_meta.get("date")
                    if not meta_data.get("time") and tpl_meta.get("time"):
                         meta_data["time"] = tpl_meta.get("time")


            final_payload = {
                "content": report_content_str,
                "title": meta_data.get("title"),
                "tags": meta_data.get("tags", []),
                "location": meta_data.get("location"),
                "time": meta_data.get("time"),
                "report_type": template_title,
                "original_transcript": updated_state.get_value("original_transcript") or transcript
            }

            final_text = json.dumps(final_payload, ensure_ascii=False)

            logger.info("Return Final Report with Metadata")
            logger.info(f"Final Payload Keys: {final_payload.keys()}")
            await event_queue.enqueue_event(new_agent_text_message(final_text))

        except Exception as exc:
            logger.error("Orchestrator-Executor failed: %s", exc, exc_info=True)
            error_response = {
                "error": str(exc),
                "type": "orchestrator_error",
                "status": "error"
            }
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(error_response, ensure_ascii=False))
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Orchestrator Agent wurde gecancelt")