'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useExecutionStatus, type ExecutionEvent } from '@/hooks'

interface TimelineStep {
  id: string
  agentId: string
  status: 'pending' | 'running' | 'complete' | 'error'
  startedAt: string | null
  completedAt: string | null
  error?: string
}

interface ExecutionTimelineProps {
  executionId: string
}

export function ExecutionTimeline({ executionId }: ExecutionTimelineProps) {
  const [steps, setSteps] = useState<TimelineStep[]>([])
  const { data: event, isConnected } = useExecutionStatus(executionId)

  useEffect(() => {
    if (!event) return

    setSteps((prev) => {
      const existing = prev.find((s) => s.agentId === event.agent_id)

      if (event.type === 'start') {
        if (existing) {
          return prev.map((s) =>
            s.agentId === event.agent_id
              ? { ...s, status: 'running', startedAt: event.timestamp }
              : s
          )
        }
        return [
          ...prev,
          {
            id: crypto.randomUUID(),
            agentId: event.agent_id || 'unknown',
            status: 'running',
            startedAt: event.timestamp,
            completedAt: null,
          },
        ]
      }

      if (event.type === 'complete') {
        return prev.map((s) =>
          s.agentId === event.agent_id
            ? { ...s, status: 'complete', completedAt: event.timestamp }
            : s
        )
      }

      if (event.type === 'error') {
        return prev.map((s) =>
          s.agentId === event.agent_id
            ? { ...s, status: 'error', completedAt: event.timestamp, error: event.error }
            : s
        )
      }

      return prev
    })
  }, [event])

  const statusColors = {
    pending: 'bg-gray-200',
    running: 'bg-blue-500 animate-pulse',
    complete: 'bg-green-500',
    error: 'bg-red-500',
  }

  const statusIcons = {
    pending: '○',
    running: '●',
    complete: '✓',
    error: '✕',
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Execution Timeline</CardTitle>
          <span className={`text-sm ${isConnected ? 'text-green-600' : 'text-gray-400'}`}>
            {isConnected ? '● Live' : '○ Disconnected'}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {steps.length === 0 ? (
          <p className="text-gray-500 text-sm py-4 text-center">
            Waiting for execution events...
          </p>
        ) : (
          <div className="space-y-4">
            {steps.map((step, index) => (
              <div key={step.id} className="flex items-start gap-4">
                {/* Timeline connector */}
                <div className="flex flex-col items-center">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center text-white text-xs ${statusColors[step.status]}`}
                  >
                    {statusIcons[step.status]}
                  </div>
                  {index < steps.length - 1 && (
                    <div className="w-0.5 h-8 bg-gray-200 mt-1" />
                  )}
                </div>

                {/* Step content */}
                <div className="flex-1 pb-4">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">{step.agentId}</span>
                    <span className="text-xs text-gray-500">
                      {step.startedAt && new Date(step.startedAt).toLocaleTimeString()}
                    </span>
                  </div>
                  <div className="text-sm text-gray-500 mt-1">
                    {step.status === 'running' && 'Processing...'}
                    {step.status === 'complete' && step.completedAt && (
                      <span>
                        Completed at {new Date(step.completedAt).toLocaleTimeString()}
                      </span>
                    )}
                    {step.status === 'error' && (
                      <span className="text-red-600">{step.error || 'Unknown error'}</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
