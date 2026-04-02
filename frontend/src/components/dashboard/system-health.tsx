'use client'

import { useEffect, useState } from 'react'
import { MetricCard } from './metric-card'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchTelemetrySummary } from '@/lib/api'
import type { TelemetrySummary } from '@/types'

export function SystemHealth() {
  const [summary, setSummary] = useState<TelemetrySummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchTelemetrySummary()
        setSummary(data)
      } catch (error) {
        console.error('Failed to fetch telemetry summary:', error)
      } finally {
        setLoading(false)
      }
    }
    load()

    // Refresh every 30 seconds
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    )
  }

  if (!summary) {
    return <div className="text-gray-500">Failed to load system health</div>
  }

  const errorRate = summary.total_executions > 0
    ? ((summary.total_executions - (summary.total_executions * summary.success_rate_overall / 100)) / summary.total_executions * 100).toFixed(1)
    : '0'

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">System Health</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Total Executions"
          value={summary.total_executions.toLocaleString()}
          subtitle={`${summary.executions_last_hour} in last hour`}
          href="/execution"
        />
        <MetricCard
          title="Success Rate"
          value={`${summary.success_rate_overall.toFixed(1)}%`}
          trend={summary.success_rate_overall >= 90 ? 'up' : summary.success_rate_overall >= 70 ? 'neutral' : 'down'}
          href="/execution"
        />
        <MetricCard
          title="Error Rate"
          value={`${errorRate}%`}
          trend={Number(errorRate) <= 5 ? 'up' : Number(errorRate) <= 15 ? 'neutral' : 'down'}
          href="/execution"
        />
        <MetricCard
          title="Avg Latency"
          value={summary.avg_latency_ms ? `${Math.round(summary.avg_latency_ms)}ms` : '-'}
          subtitle={summary.avg_latency_last_hour ? `${Math.round(summary.avg_latency_last_hour)}ms last hr` : undefined}
          href="/execution"
        />
      </div>
    </div>
  )
}
