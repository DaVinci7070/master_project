'use client'

import { useSSE } from './useSSE'

export interface ExecutionEvent {
  type: 'start' | 'progress' | 'complete' | 'error' | 'agent_start' | 'agent_complete' | 'agent_error'
  execution_id: string
  agent_id?: string
  agent_name?: string
  wave?: number
  timestamp: string
  data?: Record<string, unknown>
  error?: string
}

export function useExecutionStatus(executionId?: string) {
  const url = executionId
    ? `/api/backend/events/execution/${executionId}`
    : '/api/backend/events/executions'

  return useSSE<ExecutionEvent>(url, {
    enabled: true,
  })
}
