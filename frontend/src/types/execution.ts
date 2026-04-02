// Execution types from telemetry_schemas.py and analysis_schemas.py

export type OutcomeType = 'success' | 'error' | 'timeout' | 'cancelled'

export interface ExecutionTelemetry {
  id: string
  agent_id: string
  execution_id: string
  started_at: string
  completed_at: string | null
  latency_ms: number | null
  tokens_input: number
  tokens_output: number
  tokens_total: number
  input_hash: string
  output_hash: string | null
  outcome: OutcomeType
  error_message: string | null
  error_type: string | null
  trace_id: string | null
  span_id: string | null
  execution_metadata: Record<string, unknown>
}

export interface TelemetrySummary {
  total_executions: number
  executions_last_hour: number
  executions_last_24h: number
  success_rate_overall: number
  success_rate_last_hour: number | null
  avg_latency_ms: number | null
  avg_latency_last_hour: number | null
  total_tokens_consumed: number
  tokens_last_hour: number
  unique_agents: number
  most_active_agent_id: string | null
  last_execution_at: string | null
}

export type ConfidenceLevel = 'CAN_DO' | 'MAYBE' | 'CANNOT_DO'
export type GapSeverity = 'critical' | 'important' | 'minor'
export type GapType =
  | 'missing_skill'
  | 'weak_prompt'
  | 'topology_issue'
  | 'missing_agent'
  | 'schema_mismatch'

export interface CapabilityGap {
  gap_type: GapType
  severity: GapSeverity
  description: string
  affected_capability: string
  occurrence_count: number
}

export interface CapabilityAssessment {
  confidence: ConfidenceLevel
  reasoning: string
  top_factors: string[]
  gaps: CapabilityGap[]
  improvement_suggestions: string[]
  similar_past_success: boolean
  challenge_embedding_id: string | null
}

export interface BuildPlanItem {
  action_type: 'create_skill' | 'improve_prompt' | 'create_agent' | 'update_topology'
  target_capability: string
  description: string
  estimated_complexity: 'low' | 'medium' | 'high'
  affected_agents: string[]
  gap_severity: string
}

export interface BuildPlan {
  challenge_id: string
  items: BuildPlanItem[]
  total_gaps: number
  critical_gaps: number
  confidence_after_build: string
  created_at: string
}

export type BuildPlanStatus = 'pending' | 'approved' | 'rejected' | 'in_progress' | 'completed' | 'failed'

export interface ChallengeAnalysisResponse {
  challenge_id: string  // ID for executing this challenge
  assessment: CapabilityAssessment
  challenge_text: string
  execution_id: string
  analyzed_at: string
  route_decision: 'execute' | 'developer_team'
  // Build plan fields (only populated when route_decision === 'developer_team')
  build_plan?: BuildPlan | null
  build_plan_status?: BuildPlanStatus | null
  auto_apply_enabled?: boolean
  message?: string
}

export interface ChallengeExecutionResponse {
  challenge_id: string
  execution_id: string
  status: string
  message: string
  started_at: string
}

export interface ChallengeResultsResponse {
  challenge_id: string
  execution_id: string
  status: string
  execution_results: Record<string, unknown> | null
  duration_ms: number | null
  agents_executed: number
  completed_at: string | null
}

export type ChallengeStatus = 'pending' | 'in_progress' | 'resolved' | 'failed'

export interface BlockedChallenge {
  id: string
  execution_id: string
  project_id: string
  challenge_text: string
  assessment_result: Record<string, unknown>
  gaps_snapshot: Record<string, unknown>[]
  status: ChallengeStatus
  attempt_number: number
  max_attempts: number
  built_capability_ids: string[]
  execution_results: Record<string, unknown> | null
  created_at: string
  updated_at: string | null
  resolved_at: string | null
  failure_reasons: string[]
}
