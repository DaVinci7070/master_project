# FutureContextManager: Context Rollover Strategy

This document outlines the design for a "Context Rollover" system to prevent context rot in long-running agent sessions, inspired by patterns used in tools like Claude Code.

## 1. The Problem: Context Rot
As conversations grow, the LLM context window fills up. This leads to:
- **Performance Degradation**: Longer processing times.
- **"Rot"**: The model becomes confused by contradictory or obsolete information in the history.
- **Hard Limits**: Hitting the maximum token limit (e.g., 8192 or 128k tokens) crashes the session.

## 2. The Solution: Context Rollover (Snapshot & Reset)
Instead of a sliding window or simple summarization, we implement a **Snapshot & Reset** lifecycle. When the context approaches a threshold, we:
1.  **Pause**: Stop accepting new user input.
2.  **Snapshot**: Serialize the current "Project State" (Artifacts, Plan, Current Step).
3.  **Summarize**: Generate a high-level "Narrative Summary" of *how* we got here (decisions made, user clarifications).
4.  **Reset**: Clear the raw message history.
5.  **Respawn**: Start a new context window populated *only* with:
    - The System Prompt.
    - The Narrative Summary.
    - The Serialized State.

## 3. Architecture

### 3.1 `ContextRolloverManager`
A new utility class in `a2a_common/context_manager.py`.

**Configuration:**
- `token_threshold`: When to trigger (e.g., 80% of max context).
- `reset_overhead`: Reserve space for the summary/state.
- `keep_recent_messages`: Number of recent messages to keep "raw" (e.g., last 2) to maintain immediate flow.

**Core Methods:**
- `check_health(history: List[Message]) -> ContextHealthStatus`
    - Returns `OK` or `NEEDS_ROLLOVER`.
- `perform_rollover(state: OrchestrationState, history: List[Message]) -> List[Message]`
    - Executes the summarization and reset logic.

### 3.2 The Rollover Process

#### Step A: Summarization
The Manager calls the LLM with a specific prompt:
> "Analyze the conversation history. Summarize the key decisions, user clarifications, and current goals. Ignore obsolete chitchat. This summary will be used to initialize a fresh session."

#### Step B: State Serialization
We take the `OrchestrationState` (which contains the `Plan`, `Results`, and `Artifacts`) and format it into a compact JSON or Markdown block.

#### Step C: The "Respawn" Prompt
The new message history starts like this:

**System:**
(Original System Prompt)

**User:**
(Hidden / System Injection)
> **SYSTEM NOTICE: CONTEXT RESTORED**
> 
> The previous session was archived to save memory. Here is the current status:
> 
> **1. Session Summary:**
> {narrative_summary}
> 
> **2. Project State:**
> {serialized_state}
> 
> **3. Immediate Next Step:**
> {current_plan_step}
> 
> Please continue execution from this point.
> (User Question: "What's next?")

### 3.3 Integration Points
- **Orchestrator (`executor.py`)**:
    - In the main execution loop (or before sending a request to the Planner), call `check_health`.
    - If `NEEDS_ROLLOVER`, await `perform_rollover` and update the local `messages` list.

## 4. Implementation Stages

### Phase 1: The Token Watchdog
- Implement `ContextRolloverManager` with a simple counter.
- Log warnings when context is > 50%, > 80%.

### Phase 2: The Summarizer
- Implement the `summarize_history()` method using the LLM.
- Test that it captures critical user instructions (e.g., "Don't use class X").

### Phase 3: The Reset
- Implement the history clearing and injection of the summary.
- Verify that the agent "remembers" the plan after the reset.

## 5. Benefits
- **Infinite Sessions**: The agent can run indefinitely as long as the *State* + *Summary* fits in context.
- **Cost Efficiency**: Reduces input tokens for long sessions.
- **Stability**: Removes "noise" from early in the conversation that often distracts the model.
