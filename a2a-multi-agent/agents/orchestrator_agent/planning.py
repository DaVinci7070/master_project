# backend/orchestrator_agent/planning.py

from __future__ import annotations

from __future__ import annotations

import uuid
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from a2a_common.logging import get_logger
from a2a_common.agent_registry import AgentRegistry, AgentConfig
from a2a_common.remote_agent import RemoteAgent
from a2a_common.package_builder import AgentPackageBuilder, PackageBuildError
from a2a_common.signals import SignalType
from VLLM_Client.VLLMClient import VLLMClient

from .artifacts import (
    PlanStep,
    StepResult,
    StepStatus,
    OrchestrationStatus,
    OrchestrationState,
    OrchestrationArtifact
)
from .persistence import save_state

logger = get_logger(__name__)



PLAN_PROMPT = """Du bist ein autonomer Orchestrator für ein Multi-Agent-System auf Baustellen.

VERFÜGBARE AGENTEN:
{agent_catalog}

VORHANDENE ARTEFAKTE:
{artifact_catalog}

TRANSKRIPT-VORSCHAU (erste 2000 Zeichen):
{transcript_preview}

ZIEL: {goal}

DEINE AUFGABE:
Analysiere das Transkript und erstelle einen optimalen Ausführungsplan.
Du entscheidest SELBSTSTÄNDIG, welche Agenten benötigt werden.

ENTSCHEIDUNGSLOGIK:
1. TEMPLATE: Benötigen wir ein Template für den Bericht? → agent_template
2. VOLLSTÄNDIGKEIT: Fehlen wichtige Informationen? → agent_question (HITL)
3. SPEZIALISIERUNG - Analysiere den Inhalt:
   - Werden Mängel, Risse, Feuchtigkeit oder Schäden erwähnt? → agent_defect
   - Gibt es Sicherheitsthemen (Unfälle, Gefahren, PSA)? → agent_safety
   - Werden Nachträge, Regiearbeiten oder Zusatzleistungen erwähnt? → agent_claim
   - Gibt es technische Details (DIN-Normen, Materialien, Prüfungen)? → agent_quality
4. KONTEXT: Reichere den Text mit historischen Daten an → agent_rag
5. BERICHT: Finale Berichtserstellung → agent_summarizer
6. VALIDIERUNG: Qualitätsprüfung auf Halluzinationen → agent_guard

ABHÄNGIGKEITEN (WICHTIG):
- agent_summarizer benötigt template_result → agent_template muss vorher laufen
- agent_guard benötigt summary_report → agent_summarizer muss vorher laufen
- agent_question benötigt template_result → agent_template muss vorher laufen
- Spezialisierte Agenten (defect, safety, claim, quality) sollten VOR agent_summarizer laufen
- agent_rag MUSS zwingend VOR agent_summarizer laufen (liefert context_documents)

REGELN:
- Wähle NUR die notwendigen Agenten basierend auf dem Transkript-Inhalt
- Spezialisierte Agenten nur einbauen, wenn das Thema im Transkript vorkommt
- agent_template und agent_summarizer sind fast immer nötig
- agent_question wenn Infos fehlen
- Typische Reihenfolge: agent_template → agent_question → [spez. Agenten] → agent_rag → agent_summarizer → agent_guard
"""




class OrchestrationPlanner:
    def __init__(self, llm: VLLMClient, registry: AgentRegistry, remote_agents: Dict[str, RemoteAgent]) -> None:
        self.llm = llm
        self.registry = registry
        self.remote_agents = remote_agents
        self.package_builder = AgentPackageBuilder(registry)

    def _build_agent_catalog_text(self) -> str:
        agents = self.registry.getAllAgents()
        lines = []
        for key, entry in agents.items():
            lines.append(f'- "{key}": {entry.description}')
        return "\n".join(lines)

    def _build_artifact_catalog_text(self, state: OrchestrationState) -> str:
        if not state.artifacts: return "- (keine)"
        return "\n".join([f'- "{k}": {a.kind}' for k, a in state.artifacts.items()])

    def _resolve_semantic_mappings(self, agent_cfg: AgentConfig, state: OrchestrationState, virtual_artifacts: set[str]) -> Dict[str, str]:
        """
        Generische Mapping-Logik basierend auf Metadaten (Hints).
        """
        mappings = {}
        def _exists(key: str) -> bool: return state.has_artifact(key) or key in virtual_artifacts

        for slot_name, slot_cfg in agent_cfg.input_slots.items():
            artifact_key = None

            for hint in (slot_cfg.artifact_hints or []):
                if _exists(hint): artifact_key = hint; break
                for art in state.artifacts.values():
                    if hint in art.tags: artifact_key = art.key; break
                if artifact_key: break

            if not artifact_key and slot_cfg.default_artifact_key and _exists(slot_cfg.default_artifact_key):
                artifact_key = slot_cfg.default_artifact_key
            if not artifact_key and _exists(slot_name): artifact_key = slot_name

            if not artifact_key:
                sn = slot_name.lower()
                slot_type = getattr(slot_cfg, 'type', 'any').lower()
                
                if "transcript" in sn: 
                    artifact_key = "original_transcript" if _exists("original_transcript") else None
                elif "text" in sn and "context" not in sn: 
                    artifact_key = "original_transcript" if _exists("original_transcript") else None
                elif "template" in sn and slot_type in ("json", "any"): 
                    artifact_key = "template_result" if _exists("template_result") else None
                elif "report" in sn and slot_type in ("text", "any"): 
                    artifact_key = "final_report" if _exists("final_report") else ("summary_report" if _exists("summary_report") else None)

            if artifact_key: mappings[slot_name] = artifact_key
        return mappings

    def _apply_contracts_to_plan(self, steps: List[PlanStep], state: OrchestrationState) -> List[PlanStep]:
        agents_cfg = self.registry.getAllAgents()
        fixed_steps = []
        virtual_artifacts = set(state.artifacts.keys())
        for step in steps:
            agent_id = step.agent_id
            cfg = agents_cfg.get(agent_id)
            if not cfg and not agent_id.startswith("agent_"):

                agent_id = f"agent_{agent_id}"
                cfg = agents_cfg.get(agent_id)
                if cfg:
                    step.agent_id = agent_id  
            
            if not cfg:
                logger.warning(f"DEBUG: Agent '{step.agent_id}' not found in registry. Skipping step.")
                continue
            step_copy = step.model_copy(deep=True)
            step_copy.input_mapping = self._resolve_semantic_mappings(cfg, state, virtual_artifacts)
            for slot_name, out_cfg in cfg.output_slots.items():
                target_key = step_copy.output_mapping.get(slot_name) or out_cfg.default_artifact_key or f"{step.agent_id}_{slot_name}"
                virtual_artifacts.add(target_key)
                step_copy.output_mapping[slot_name] = target_key
            fixed_steps.append(step_copy)

        # Hard-enforce ordering constraints: agent_rag must always precede agent_summarizer
        fixed_steps = self._enforce_ordering(fixed_steps)
        return fixed_steps

    def _enforce_ordering(self, steps: List[PlanStep]) -> List[PlanStep]:
        """Ensures that agent_rag always runs before agent_summarizer."""
        BEFORE_AFTER = [("agent_rag", "agent_summarizer")]
        for before, after in BEFORE_AFTER:
            before_idx = next((i for i, s in enumerate(steps) if s.agent_id == before), None)
            after_idx = next((i for i, s in enumerate(steps) if s.agent_id == after), None)
            if before_idx is not None and after_idx is not None and before_idx > after_idx:
                logger.warning(
                    f"Ordering fix: moving {before} (idx={before_idx}) before {after} (idx={after_idx})"
                )
                step_to_move = steps.pop(before_idx)
                steps.insert(after_idx, step_to_move)
        return steps

    def create_plan(self, state: OrchestrationState) -> List[PlanStep]:

        transcript = state.get_value("original_transcript") or ""
        transcript_preview = transcript[:2000] if transcript else "(kein Transkript verfügbar)"
        
        prompt = PLAN_PROMPT.format(
            goal=state.goal,
            agent_catalog=self._build_agent_catalog_text(),
            artifact_catalog=self._build_artifact_catalog_text(state),
            transcript_preview=transcript_preview
        )
        

        class ExecutionPlan(BaseModel):
            reasoning: str = ""
            steps: List[PlanStep]

        try:
            logger.debug(f"Generating autonomous plan for goal: {state.goal}")
            plan_result = self.llm.generate_structured(
                response_model=ExecutionPlan,
                prompt=prompt, 
                temperature=0.2,  
                max_tokens=1500
            )
            

            if plan_result.reasoning:
                logger.info(f"🧠 Orchestrator Reasoning: {plan_result.reasoning}")
                state.set_artifact("plan_reasoning", plan_result.reasoning, kind="text")
            
            steps = plan_result.steps
            logger.info(f"DEBUG: Generated steps: {[s.agent_id for s in steps]}")
            
            final_steps = self._apply_contracts_to_plan(steps, state)
            plan_str = " > ".join([s.agent_id for s in final_steps])
            logger.info(f"\n \n Plan: {plan_str}\n \n")
 
            return final_steps
        except Exception as e:
            logger.error(f"Planungsfehler: {e}")
            return []


    async def run(self, state: OrchestrationState, event_queue: Optional[EventQueue] = None) -> OrchestrationState:
        if not state.plan:
            state.plan = self.create_plan(state)
            if not state.plan:
                state.status = OrchestrationStatus.FAILED
                return state
            state.current_step_idx = 0
            state.status = OrchestrationStatus.PENDING
        
        logger.info(f"DEBUG: Planning Start. Available Artifacts: {list(state.artifacts.keys())}")

        agents_cfg = self.registry.getAllAgents()


        while state.current_step_idx < len(state.plan):
            step = state.plan[state.current_step_idx]
            agent = self.remote_agents.get(step.agent_id)
            cfg = agents_cfg.get(step.agent_id)
            
            if not agent or not cfg:
                state.current_step_idx += 1; continue


            step_result = StepResult(step_id=step.step_id, agent_id=step.agent_id)
            logger.info(f"Step {step.agent_id}: Input Mapping: {step.input_mapping}")
            

            try:

                artifacts_dict = {k: state.get_value(k) for k in state.artifacts.keys() if state.get_value(k) is not None}


                validated_input = self.package_builder.build_package(
                    agent_id=step.agent_id,
                    artifacts=artifacts_dict,
                    input_mapping=step.input_mapping,
                )
                

                for field_name in validated_input.model_fields.keys():
                    value = getattr(validated_input, field_name)
                    if value is not None:
                        step_result.input_artifacts[field_name] = field_name
                
                logger.info(f"Built validated package for {step.agent_id}: {list(validated_input.model_fields.keys())}")

            except PackageBuildError as e:
                logger.error(f"Integrity Check Failed for {step.agent_id}: {e}")
                raise e 

            except Exception as e:
                logger.error(f"Error building package for {step.agent_id}: {e}")
                raise e


            try:

                output_schema = self.registry.get_output_schema(step.agent_id)
                if not output_schema:
                    raise ValueError(f"No output schema defined for {step.agent_id}")


                output, signal = await agent.call_structured(
                    output_schema=output_schema,
                    input_data=validated_input,
                    correlation_id=state.run_id
                )

                logger.info(f"DEBUG: Received from {step.agent_id}: output={output.__class__.__name__}, signal={signal.signal if signal else None}")


                if signal and signal.signal == SignalType.SUSPEND:
                    logger.info(f"⏸️ SUSPEND Signal from {step.agent_id}: {signal.reason}")
                    state.status = OrchestrationStatus.WAITING_FOR_USER
                    
                    if signal.data:
                        state.set_artifact("question_result", signal.data, kind="json", tags=["hitl"])
                    
                    step_result.mark_finished(StepStatus.SKIPPED, error_message="Suspended for User Input")
                    state.add_step_result(step_result)

                    await save_state(state)
                    return state
                
                if signal and signal.signal == SignalType.ERROR:
                    reason = signal.reason or "Unknown agent error"
                    logger.error(f"❌ ERROR Signal from {step.agent_id}: {reason}")
                    step_result.mark_finished(StepStatus.ERROR, error_message=reason)
                    state.add_step_result(step_result)
                    state.status = OrchestrationStatus.FAILED
                    await save_state(state)
                    return state


                output_data = output.model_dump()
                for field_name, value in output_data.items():
                    if value is not None:

                        target_key = step.output_mapping.get(field_name, field_name)
                        state.set_artifact(
                            target_key,
                            value,
                            kind="json" if isinstance(value, (dict, list)) else "text"
                        )
                        step_result.output_artifacts[field_name] = target_key
                        value_info = f"len={len(value)}" if isinstance(value, (list, str)) else f"type={type(value).__name__}"
                        logger.info(f"✓ Artifact stored: {target_key} ({value_info})")

                step_result.mark_finished(StepStatus.SUCCESS)
                state.add_step_result(step_result)

                state.current_step_idx += 1
                logger.info(f"✅ Step {step.step_id} finished.")

            except Exception as e:
                logger.error(f"Execution Error at {step.agent_id}: {e}")
                step_result.mark_finished(StepStatus.ERROR, error_message=str(e))
                state.add_step_result(step_result)

                state.status = OrchestrationStatus.FAILED
                await save_state(state)
                return state

        state.status = OrchestrationStatus.COMPLETED
        await save_state(state)
        return state