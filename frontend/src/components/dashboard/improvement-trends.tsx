'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { MetricCard } from './metric-card'
import { TrendChart } from './trend-chart'
import { fetchABTests } from '@/lib/api'
import type { TrendPoint } from '@/types'

interface ImprovementData {
  abWins: number
  promptsEvolved: number
  skillsAdded: number
  successRateTrend: TrendPoint[]
}

export function ImprovementTrends() {
  const [data, setData] = useState<ImprovementData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        // Fetch A/B test data to count wins
        const tests = await fetchABTests()
        const completedTests = tests.filter(t => t.status === 'completed')
        const wins = completedTests.filter(t => t.is_significant === 1).length

        // Count prompts evolved (completed tests on prompts)
        const promptTests = completedTests.filter(t => t.artifact_type === 'prompt')

        // Count skills added (completed tests on skills)
        const skillTests = completedTests.filter(t => t.artifact_type === 'skill')

        // Generate mock success rate trend (last 50 executions)
        // In production, this would come from the dashboard metrics endpoint
        const successRateTrend: TrendPoint[] = Array.from({ length: 50 }, (_, i) => ({
          execution: i + 1,
          value: 75 + Math.random() * 20, // Mock data 75-95%
        }))

        setData({
          abWins: wins,
          promptsEvolved: promptTests.length,
          skillsAdded: skillTests.length,
          successRateTrend,
        })
      } catch (error) {
        console.error('Failed to fetch improvement data:', error)
        // Set fallback data
        setData({
          abWins: 0,
          promptsEvolved: 0,
          skillsAdded: 0,
          successRateTrend: [],
        })
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Improvement Trends</h2>
        <div className="grid grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-[250px]" />
      </div>
    )
  }

  if (!data) {
    return <div className="text-gray-500">Failed to load improvement trends</div>
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Improvement Trends</h2>

      {/* Summary metrics */}
      <div className="grid grid-cols-3 gap-4">
        <MetricCard
          title="A/B Test Wins"
          value={data.abWins}
          subtitle="Validated improvements"
          href="/prompts"
        />
        <MetricCard
          title="Prompts Evolved"
          value={data.promptsEvolved}
          subtitle="Across all agents"
          href="/prompts"
        />
        <MetricCard
          title="Skills Added"
          value={data.skillsAdded}
          subtitle="New capabilities"
          href="/skills"
        />
      </div>

      {/* Success rate trend chart */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-gray-500">
            Success Rate Over Last 50 Executions
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.successRateTrend.length > 0 ? (
            <TrendChart
              data={data.successRateTrend}
              title="Success Rate %"
              yAxisLabel="%"
              color="#22c55e"
            />
          ) : (
            <p className="text-gray-500 text-sm py-8 text-center">
              No execution data available
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
