// Evaluation Dashboard types

export interface SuiteInfo {
  name: string
  description: string | null
  task_count: number
}

export interface SuiteTaskInfo {
  task_id: string
  level: string
  description: string
  keywords_count: number
  sections_count: number
}

export interface SuiteDetailResponse {
  name: string
  description: string | null
  tasks: SuiteTaskInfo[]
}

export interface SnapshotInfo {
  filename: string
  size_bytes: number
  modified_at: string
}

export interface ColdResetRequest {
  skip_seed?: boolean
  skip_qdrant?: boolean
  dry_run?: boolean
}

export interface ColdResetResponse {
  tables_truncated: number
  qdrant_cleared: string[]
  agents_seeded: number
  dry_run: boolean
}

export interface WarmSaveResponse {
  pg_dump: string
  qdrant_snapshots: string[]
}

export interface WarmRestoreResponse {
  restored_from: string
  returncode: number
}

export interface StartRunRequest {
  suite: string
  ablation_mode?: string | null
  seed?: number
  timeout?: number
  poll_interval?: number
  project_id?: string
}

export interface StartRunResponse {
  run_id: string
  status: string
}

export interface EvalTaskProgress {
  task_id: string
  level: string
  status: 'pending' | 'running' | 'passed' | 'failed' | 'error' | 'timeout' | 'resolved'
  duration_ms: number
  pass_result: boolean | null
  score: number
  error: string | null
  missing_keywords?: string[]
  missing_sections?: string[]
  tokens_total?: number
  tokens_input?: number
  tokens_output?: number
  agents_executed?: number
  challenge_id?: string | null
}

export interface EvalRunSummary {
  run_id: string
  suite: string
  ablation_mode: string | null
  status: string
  tasks_total: number
  tasks_completed: number
  tasks_passed: number
  pass_at_1: number
  started_at: string
  completed_at: string | null
}

export interface EvalRunDetail {
  run_id: string
  suite: string
  ablation_mode: string | null
  seed: number | null
  status: string
  started_at: string
  completed_at: string | null
  tasks_total: number
  tasks_passed: number
  pass_at_1: number
  total_tokens: number
  total_tokens_input: number
  total_tokens_output: number
  total_duration_ms: number
  avg_score: number
  task_results: EvalTaskProgress[]
  error?: string | null
}

export type AblationModes = Record<string, Record<string, string>>
