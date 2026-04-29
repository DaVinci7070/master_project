'use client'

import { useState, useCallback } from 'react'
import { useSSE } from './useSSE'
import type { EvalTaskProgress } from '@/types'

interface EvalSSEEvent {
  // task_complete fields
  index?: number
  task_id?: string
  level?: string
  status?: string
  duration_ms?: number
  pass_result?: boolean | null
  error?: string | null
  tasks_completed?: number
  tasks_total?: number
  pass_at_1?: number
  // run_complete fields
  run_id?: string
  suite?: string
  ablation_mode?: string | null
  completed_at?: string | null
}

interface UseEvalRunStreamReturn {
  taskProgress: EvalTaskProgress[]
  tasksCompleted: number
  tasksTotal: number
  passAt1: number
  runStatus: 'idle' | 'running' | 'completed' | 'failed'
  isConnected: boolean
  error: Error | null
  startStream: (runId: string, initialTasks: EvalTaskProgress[]) => void
  reset: () => void
}

export function useEvalRunStream(): UseEvalRunStreamReturn {
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [taskProgress, setTaskProgress] = useState<EvalTaskProgress[]>([])
  const [tasksCompleted, setTasksCompleted] = useState(0)
  const [tasksTotal, setTasksTotal] = useState(0)
  const [passAt1, setPassAt1] = useState(0)
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>('idle')

  const { error, isConnected } = useSSE<EvalSSEEvent>(
    activeRunId ? `/api/backend/evaluation/runs/${activeRunId}/stream` : '',
    {
      enabled: !!activeRunId && runStatus === 'running',
      eventTypes: ['task_complete', 'run_complete', 'heartbeat', 'error'],
      onMessage: (event) => {
        if (event.task_id && event.index !== undefined) {
          // task_complete event
          setTaskProgress((prev) => {
            const updated = [...prev]
            updated[event.index!] = {
              task_id: event.task_id!,
              level: event.level || '',
              status: event.status as EvalTaskProgress['status'],
              duration_ms: event.duration_ms || 0,
              pass_result: event.pass_result ?? null,
              error: event.error ?? null,
            }
            return updated
          })
          if (event.tasks_completed !== undefined) setTasksCompleted(event.tasks_completed)
          if (event.tasks_total !== undefined) setTasksTotal(event.tasks_total)
          if (event.pass_at_1 !== undefined) setPassAt1(event.pass_at_1)
        }

        if (event.run_id && event.completed_at) {
          // run_complete event
          const status = event.status === 'failed' ? 'failed' : 'completed'
          setRunStatus(status)
          if (event.pass_at_1 !== undefined) setPassAt1(event.pass_at_1)
          setActiveRunId(null)
        }
      },
    }
  )

  const startStream = useCallback((runId: string, initialTasks: EvalTaskProgress[]) => {
    setTaskProgress(initialTasks)
    setTasksCompleted(0)
    setTasksTotal(initialTasks.length)
    setPassAt1(0)
    setRunStatus('running')
    setActiveRunId(runId)
  }, [])

  const reset = useCallback(() => {
    setActiveRunId(null)
    setTaskProgress([])
    setTasksCompleted(0)
    setTasksTotal(0)
    setPassAt1(0)
    setRunStatus('idle')
  }, [])

  return {
    taskProgress,
    tasksCompleted,
    tasksTotal,
    passAt1,
    runStatus,
    isConnected,
    error,
    startStream,
    reset,
  }
}
