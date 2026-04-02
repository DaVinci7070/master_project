// Metrics types from ab_test_schemas.py and telemetry_schemas.py

export type ArtifactType = 'prompt' | 'agent' | 'skill'
export type TestStatus = 'pending' | 'running' | 'completed' | 'cancelled'

export interface ABTest {
  id: string
  improvement_attempt_id: string
  artifact_type: ArtifactType
  artifact_id: string
  version_baseline: number
  version_improvement: number
  metric_weights: Record<string, number>
  status: TestStatus
  samples_baseline: number
  samples_improvement: number
  p_value: number | null
  effect_size: number | null
  is_significant: number | null
  confidence_interval_low: number | null
  confidence_interval_high: number | null
  created_at: string
  completed_at: string | null
  queued_ids: string[]
}

export interface TelemetryAggregation {
  agent_id: string
  total_executions: number
  successful_executions: number
  failed_executions: number
  timeout_executions: number
  cancelled_executions: number
  success_rate: number
  avg_latency_ms: number | null
  min_latency_ms: number | null
  max_latency_ms: number | null
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  p99_latency_ms: number | null
  total_tokens_input: number
  total_tokens_output: number
  total_tokens: number
  avg_tokens_per_execution: number | null
  period_start: string | null
  period_end: string | null
}

// Dashboard-specific types for runs-based metrics (per CONTEXT)
export interface DashboardMetrics {
  system_health: SystemHealth
  improvement_trends: ImprovementTrends
}

export interface SystemHealth {
  active_executions: number
  error_rate_last_n: number
  avg_latency_last_n: number
  uptime_percentage: number
}

export interface ImprovementTrends {
  ab_wins_last_n: number
  prompts_evolved: number
  skills_added: number
  success_rate_trend: TrendPoint[]
}

export interface TrendPoint {
  execution: number
  value: number
}
