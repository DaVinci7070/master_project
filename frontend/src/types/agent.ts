// Agent types from versioned_schemas.py

export type AgentSource = 'initial' | 'system_generated' | 'manual'

export interface Agent {
  id: string
  name: string
  capabilities: string[]
  dependencies: string[]
  io_schema: Record<string, unknown>
  is_active: boolean
  prompt_id: string | null
  source: AgentSource
  agent_metadata?: Record<string, unknown> | null
  created_at: string
}

export interface Skill {
  id: string
  parent_id: string | null
  name: string
  description: string | null
  code?: string  // Optional - not in summary response
  test_cases?: SkillTestCase[]  // Optional - not in summary response
  test_count?: number  // In summary response
  skill_metadata?: Record<string, unknown>  // Optional - not in summary response
  is_active: boolean
  created_at: string
  health_status?: string  // In summary response
}

export interface SkillTestCase {
  name: string
  input: Record<string, unknown>
  expected_output: unknown
  description?: string
}

export interface Prompt {
  id: string
  parent_id: string | null
  name: string
  content?: string
  content_preview?: string
  prompt_metadata?: Record<string, unknown>
  is_active: boolean
  created_at: string
}
