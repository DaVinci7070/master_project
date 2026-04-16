// API client with typed fetch functions
import type {
  Agent,
  Skill,
  Prompt,
  TelemetrySummary,
  ExecutionTelemetry,
  Topology,
  ABTest,
  ChallengeAnalysisResponse,
  ChallengeExecutionResponse,
  BlockedChallenge,
  DashboardMetrics,
} from '@/types'

const API_BASE = '/api/backend'

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`)
  }

  return response.json()
}

// Agent operations
export async function fetchAgents(): Promise<Agent[]> {
  const response = await fetchJson<{ agents: Agent[]; total: number }>('/agents')
  return response.agents
}

// Skill operations
export async function fetchSkills(): Promise<Skill[]> {
  const response = await fetchJson<{ skills: Skill[]; total: number }>('/skills')
  return response.skills
}

export async function fetchSkill(id: string): Promise<Skill> {
  return fetchJson<Skill>(`/skills/${id}`)
}

export async function updateSkill(id: string, data: Partial<Skill>): Promise<Skill> {
  return fetchJson<Skill>(`/skills/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

// Prompt operations
export async function fetchPrompts(): Promise<Prompt[]> {
  const response = await fetchJson<{ prompts: Prompt[]; total: number }>('/prompts')
  return response.prompts
}

export async function fetchPrompt(id: string): Promise<Prompt> {
  return fetchJson<Prompt>(`/prompts/${id}`)
}

export async function fetchPromptVersions(id: string): Promise<Prompt[]> {
  return fetchJson<Prompt[]>(`/prompts/${id}/versions`)
}

// Telemetry operations
export async function fetchTelemetrySummary(): Promise<TelemetrySummary> {
  return fetchJson<TelemetrySummary>('/telemetry/summary')
}

export async function fetchRecentExecutions(
  limit: number = 50
): Promise<ExecutionTelemetry[]> {
  const response = await fetchJson<{ executions: ExecutionTelemetry[]; total: number }>(`/telemetry/executions?limit=${limit}`)
  return response.executions
}

// Topology operations
export async function fetchTopology(): Promise<Topology> {
  return fetchJson<Topology>('/topology')
}

// A/B Test operations
export async function fetchABTests(): Promise<ABTest[]> {
  const response = await fetchJson<{ tests: ABTest[]; total: number }>('/ab-tests')
  return response.tests
}

// Challenge operations
export async function submitChallenge(
  challengeText: string,
  projectId: string = 'default'
): Promise<ChallengeAnalysisResponse> {
  return fetchJson<ChallengeAnalysisResponse>('/challenges/analyze', {
    method: 'POST',
    body: JSON.stringify({
      challenge_text: challengeText,
      execution_id: crypto.randomUUID(),
      project_id: projectId,
      include_cross_project: true,
    }),
  })
}

export async function uploadChallengeFile(
  file: File,
  projectId: string = 'default',
  instructions: string = ''
): Promise<ChallengeAnalysisResponse> {
  // Send file as FormData for backend processing
  const formData = new FormData()
  formData.append('file', file)
  formData.append('project_id', projectId)
  formData.append('execution_id', crypto.randomUUID())
  if (instructions.trim()) {
    formData.append('instructions', instructions.trim())
  }

  const response = await fetch(`${API_BASE}/challenges/upload`, {
    method: 'POST',
    body: formData,
    // Don't set Content-Type - browser will set it with boundary for multipart
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `Upload failed: ${response.status}`)
  }

  return response.json()
}

// Execute challenge
export async function executeChallenge(
  challengeId: string
): Promise<ChallengeExecutionResponse> {
  return fetchJson<ChallengeExecutionResponse>(`/challenges/${challengeId}/execute`, {
    method: 'POST',
  })
}

// Get challenge status
export async function fetchChallengeStatus(
  challengeId: string
): Promise<BlockedChallenge> {
  return fetchJson<BlockedChallenge>(`/challenges/${challengeId}`)
}

// Dashboard metrics (runs-based per CONTEXT)
export async function fetchDashboardMetrics(
  lastNRuns: number = 50
): Promise<DashboardMetrics> {
  return fetchJson<DashboardMetrics>(`/dashboard/metrics?last=${lastNRuns}`)
}

// Emergency stop
export async function triggerEmergencyStop(): Promise<{
  success: boolean
  message: string
}> {
  return fetchJson<{ success: boolean; message: string }>(
    '/system/emergency-stop',
    {
      method: 'POST',
    }
  )
}

// System reset
export async function triggerSystemReset(): Promise<{
  success: boolean
  message: string
  deleted_agents: number
  deleted_skills: number
  deleted_prompts: number
  deleted_events: number
  remaining_default_agents: number
}> {
  return fetchJson('/system/reset', { method: 'POST' })
}

// Execution snapshots
export async function fetchExecutionSnapshots(): Promise<
  { id: string; created_at: string; description: string }[]
> {
  return fetchJson('/snapshots')
}

export async function createExecutionSnapshot(
  description: string
): Promise<{ id: string }> {
  return fetchJson('/snapshots', {
    method: 'POST',
    body: JSON.stringify({ description }),
  })
}

// ============================================================================
// Build Plan operations
// ============================================================================

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

export interface BuildPlanResponse {
  plan: BuildPlan
  status: 'pending' | 'approved' | 'rejected' | 'in_progress' | 'completed' | 'failed'
  auto_apply_enabled: boolean
  message: string
}

export interface UserSettings {
  auto_apply: boolean
  notify_on_build: boolean
  notify_on_execution: boolean
}

export async function fetchBuildPlan(challengeId: string): Promise<BuildPlanResponse> {
  return fetchJson<BuildPlanResponse>(`/challenges/${challengeId}/build-plan`)
}

export async function approveBuildPlan(
  challengeId: string,
  approved: boolean,
  feedback?: string
): Promise<{ status: string; message: string; challenge_id: string }> {
  return fetchJson(`/challenges/${challengeId}/build-plan/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved, feedback }),
  })
}

export async function fetchUserSettings(): Promise<UserSettings> {
  return fetchJson<UserSettings>('/challenges/settings/user')
}

export async function updateUserSettings(
  settings: Partial<UserSettings>
): Promise<UserSettings> {
  return fetchJson<UserSettings>('/challenges/settings/user', {
    method: 'PUT',
    body: JSON.stringify(settings),
  })
}

// ============================================================================
// Execution History operations
// ============================================================================

export interface ExecutionSummary {
  id: string
  challenge_id: string | null
  project_id: string
  status: string
  agents_executed: number
  waves_executed: number
  duration_ms: number | null
  error: string | null
  started_at: string
  completed_at: string | null
}

export interface ExecutionDetail extends ExecutionSummary {
  input_data: Record<string, unknown> | null
  results: Record<string, unknown> | null
  events?: AgentEvent[]
}

export interface AgentEvent {
  id: string
  agent_id: string
  agent_name: string
  event_type: string
  wave: number
  data: Record<string, unknown> | null
  error: string | null
  created_at: string
}

export interface ExecutionsResponse {
  executions: ExecutionSummary[]
  total: number
  limit: number
  offset: number
}

export async function fetchExecutions(
  limit: number = 50,
  offset: number = 0,
  status?: string,
  projectId?: string
): Promise<ExecutionsResponse> {
  let url = `/executions?limit=${limit}&offset=${offset}`
  if (status) url += `&status=${status}`
  if (projectId) url += `&project_id=${projectId}`
  return fetchJson<ExecutionsResponse>(url)
}

// ============================================================================
// Shared Memory operations
// ============================================================================

export interface SharedMemoryFact {
  id: string
  text: string
  confidence: number
  source_agent_id: string
  tags: string[]
  created_at: string
}

export interface SharedMemoryHypothesis {
  id: string
  text: string
  confidence: number
  status: string
  source_agent_id: string
  supporting_fact_ids: string[]
  contradicting_fact_ids: string[]
  created_at: string
}

export interface SharedMemoryResponse {
  execution_id: string
  facts: {
    total: number
    by_agent: Record<string, SharedMemoryFact[]>
    items: SharedMemoryFact[]
  }
  hypotheses: {
    total: number
    by_agent: Record<string, SharedMemoryHypothesis[]>
    items: SharedMemoryHypothesis[]
  }
}

export async function fetchSharedMemory(
  executionId: string
): Promise<SharedMemoryResponse> {
  return fetchJson<SharedMemoryResponse>(`/shared-memory/execution/${executionId}`)
}

