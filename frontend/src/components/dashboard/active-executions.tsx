'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useExecutionStatus } from '@/hooks'
import type { ExecutionTelemetry } from '@/types'
import { fetchRecentExecutions } from '@/lib/api'

export function ActiveExecutions() {
  const [executions, setExecutions] = useState<ExecutionTelemetry[]>([])
  const [loading, setLoading] = useState(true)
  const { data: liveEvent } = useExecutionStatus()

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchRecentExecutions(5)
        setExecutions(data)
      } catch (error) {
        console.error('Failed to fetch executions:', error)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [liveEvent]) // Refetch when live event received

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent Executions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Recent Executions</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {executions.length === 0 ? (
            <p className="text-gray-500 text-sm">No recent executions</p>
          ) : (
            executions.map((exec) => (
              <div
                key={exec.id}
                className="flex items-center justify-between py-2 border-b last:border-0"
              >
                <div>
                  <span className="font-medium text-sm">{exec.execution_id.slice(0, 8)}</span>
                  <span className="text-gray-500 text-sm ml-2">
                    {new Date(exec.started_at).toLocaleTimeString()}
                  </span>
                </div>
                <span className={`text-sm px-2 py-1 rounded ${
                  exec.outcome === 'success' ? 'bg-green-100 text-green-700' :
                  exec.outcome === 'error' ? 'bg-red-100 text-red-700' :
                  'bg-gray-100 text-gray-700'
                }`}>
                  {exec.outcome}
                </span>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  )
}
