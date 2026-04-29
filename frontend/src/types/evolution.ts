// Evolution types — mirrors backend/app/api/v1/endpoints/evolution.py and
// SkillVersionHistoryResponse in backend/app/api/v1/endpoints/skills.py.

export type EvolutionEventType =
  | 'evolution.triggered'
  | 'evolution.finding_detected'
  | 'evolution.skipped_by_strike'
  | 'evolution.prompt_updated'
  | 'evolution.skill_rebuilt'
  | 'evolution.agent_updated'
  | 'evolution.topology_changed'
  | 'evolution.completed'
  | 'evolution.failed'
  | (string & {})

export interface EvolutionEvent {
  id: string
  execution_id: string
  event_type: EvolutionEventType
  agent_id: string | null
  data: Record<string, unknown>
  created_at: string | null
}

export interface EvolutionHistoryResponse {
  execution_id: string | null
  count: number
  events: EvolutionEvent[]
}

export interface EvolutionStats {
  total_attempts: number
  by_status: Record<string, number>
  by_artifact_type: Record<string, number>
}

export interface EvolutionReport {
  execution_id: string
  attempted: number
  succeeded: number
  skipped_by_strike: number
  reason?: string | null
}

// Skill version history (Sprint 2)
export interface SkillBuildAttemptSummary {
  id: string
  attempt_number: number
  capability: string
  approach: string | null
  success: boolean
  error_type: string | null
  error_type_classified: string | null
  lesson_learned: string | null
  failure_analysis: Record<string, unknown> | null
  code_snapshot: string | null
  created_at: string
}

export interface SkillVersionEntry {
  id: string
  name: string
  version_index: number
  parent_id: string | null
  description: string | null
  is_active: boolean
  created_at: string
  build_attempts: SkillBuildAttemptSummary[]
}

export interface SkillVersionHistory {
  skill_id: string
  total_versions: number
  lineage: SkillVersionEntry[]
}

// Prompt version-history — correct shape of GET /prompts/{id}/versions.
// (The pre-existing `fetchPromptVersions` in api.ts mistypes this response;
// we avoid touching that callsite and use a new, properly-typed helper.)
export interface PromptVersionEntry {
  id: string
  name: string
  content_preview: string
  is_active: boolean
  created_at: string
  version_index: number
}

export interface PromptVersionHistory {
  prompt_id: string
  versions: PromptVersionEntry[]
  total_versions: number
}

// Topology change-history (Sprint 2 backend, consumed by Sprint-4 F9 UI).
// Mirrors TopologyHistoryEntry/TopologyHistoryResponse in
// backend/app/api/v1/endpoints/topology.py.
export interface TopologyHistoryEntry {
  id: string
  timestamp: string
  change_type: string
  description: string
  affected_agents: string[]
  entity_type: string | null
  entity_id: string | null
  entity_name: string | null
  source: string | null
  triggered_by: string | null
  change_details: Record<string, unknown> | null
  previous_state: Record<string, unknown> | null
  new_state: Record<string, unknown> | null
}

export interface TopologyHistoryResponse {
  entries: TopologyHistoryEntry[]
  total: number
}