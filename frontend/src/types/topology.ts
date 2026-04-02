// Topology types from orchestration/topology/models.py

export interface AgentNode {
  agent_id: string
  name: string
  prompt_id: string | null
  capabilities: string[]
  dependencies: string[]
  skill_ids: string[]
  config: Record<string, unknown>
  is_active: boolean
  input_schema: Record<string, unknown> | null
  output_schema: Record<string, unknown> | null
  consumes_artifacts: string[]
  produces_artifacts: string[]
}

export interface AgentEdge {
  from_agent_id: string
  to_agent_id: string
  edge_type: string
}

export interface Topology {
  topology_id: string
  name: string
  description: string | null
  agents: AgentNode[]
  created_at: string
  is_active: boolean
  version: number
}

export interface ValidationResult {
  is_valid: boolean
  execution_order: string[] | null
  execution_waves: string[][] | null
  cycle_nodes: string[] | null
  missing_dependencies: [string, string][] | null
  errors: string[]
  warnings: string[]
}
