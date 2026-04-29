'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceDot,
} from 'recharts'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useEvolutionEvents } from '@/hooks'
import {
  fetchDashboardMetrics,
  fetchEvolutionHistory,
  fetchRecentExecutions,
} from '@/lib/api'
import type { EvolutionEvent, ExecutionTelemetry, TrendPoint } from '@/types'

// ---------------------------------------------------------------- data model

interface CorrelationPoint {
  execution: number
  passRate: number
  promptVersions: number
  skillVersions: number
  hasPromptBump: boolean
  hasSkillBump: boolean
  hasTopologyChange: boolean
}

// ---------------------------------------------------------------- data merge

function buildExecutionIndexMap(
  executions: ExecutionTelemetry[]
): Map<string, number> {
  const sorted = [...executions].sort(
    (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime()
  )
  const map = new Map<string, number>()
  for (let i = 0; i < sorted.length; i++) {
    map.set(sorted[i].execution_id, i + 1)
  }
  return map
}

function groupEventsByExecution(
  events: EvolutionEvent[],
  indexMap: Map<string, number>
): Map<
  number,
  { promptBumps: number; skillBumps: number; topologyChanges: number }
> {
  const grouped = new Map<
    number,
    { promptBumps: number; skillBumps: number; topologyChanges: number }
  >()
  for (const event of events) {
    const idx = indexMap.get(event.execution_id)
    if (idx === undefined) continue
    const entry = grouped.get(idx) ?? {
      promptBumps: 0,
      skillBumps: 0,
      topologyChanges: 0,
    }
    if (event.event_type === 'evolution.prompt_updated') entry.promptBumps++
    else if (event.event_type === 'evolution.skill_rebuilt') entry.skillBumps++
    else if (event.event_type === 'evolution.topology_changed')
      entry.topologyChanges++
    else continue
    grouped.set(idx, entry)
  }
  return grouped
}

function mergeData(
  trend: TrendPoint[],
  eventGroups: Map<
    number,
    { promptBumps: number; skillBumps: number; topologyChanges: number }
  >
): CorrelationPoint[] {
  let cumulativePrompt = 0
  let cumulativeSkill = 0

  const sorted = [...trend].sort((a, b) => a.execution - b.execution)
  return sorted.map((pt) => {
    const group = eventGroups.get(pt.execution)
    const promptBumps = group?.promptBumps ?? 0
    const skillBumps = group?.skillBumps ?? 0
    const topologyChanges = group?.topologyChanges ?? 0
    cumulativePrompt += promptBumps
    cumulativeSkill += skillBumps
    return {
      execution: pt.execution,
      passRate: Math.round(pt.value * 10) / 10,
      promptVersions: cumulativePrompt,
      skillVersions: cumulativeSkill,
      hasPromptBump: promptBumps > 0,
      hasSkillBump: skillBumps > 0,
      hasTopologyChange: topologyChanges > 0,
    }
  })
}

// ---------------------------------------------------------------- custom tooltip

interface TooltipPayloadEntry {
  name: string
  value: number
  color: string
  dataKey: string
  payload: CorrelationPoint
}

function CorrelationTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: TooltipPayloadEntry[]
  label?: number
}) {
  if (!active || !payload || payload.length === 0) return null
  const point = payload[0]?.payload as CorrelationPoint | undefined
  if (!point) return null

  const events: string[] = []
  if (point.hasPromptBump) events.push('Prompt evolved')
  if (point.hasSkillBump) events.push('Skill rebuilt')
  if (point.hasTopologyChange) events.push('Topology changed')

  return (
    <div className="rounded-md border bg-background p-2 shadow-sm text-xs space-y-1">
      <p className="font-medium">Execution #{label}</p>
      {payload.map((entry) => (
        <div key={entry.dataKey} className="flex items-center gap-2">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-muted-foreground">{entry.name}:</span>
          <span className="font-medium">
            {entry.dataKey === 'passRate'
              ? `${entry.value}%`
              : entry.value}
          </span>
        </div>
      ))}
      {events.length > 0 && (
        <div className="border-t pt-1 mt-1 text-muted-foreground italic">
          {events.join(' · ')}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- custom dot

function EvolutionMarkerDot(props: {
  cx?: number
  cy?: number
  payload?: CorrelationPoint
  dataKey?: string
}) {
  const { cx, cy, payload, dataKey } = props
  if (!cx || !cy || !payload) return null

  const isPromptLine = dataKey === 'promptVersions'
  const isSkillLine = dataKey === 'skillVersions'
  const isPassLine = dataKey === 'passRate'

  const showMarker =
    (isPromptLine && payload.hasPromptBump) ||
    (isSkillLine && payload.hasSkillBump) ||
    (isPassLine && (payload.hasPromptBump || payload.hasSkillBump || payload.hasTopologyChange))

  if (!showMarker) return <circle cx={cx} cy={cy} r={2} fill="transparent" />

  const fill = isPromptLine
    ? '#6366f1'
    : isSkillLine
      ? '#f59e0b'
      : '#22c55e'

  return (
    <>
      <circle cx={cx} cy={cy} r={6} fill={fill} opacity={0.2} />
      <circle cx={cx} cy={cy} r={3} fill={fill} stroke="#fff" strokeWidth={1} />
    </>
  )
}

// ---------------------------------------------------------------- main

const EXEC_LIMIT = 50

export function MetricCorrelationChart() {
  const [data, setData] = useState<CorrelationPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { events } = useEvolutionEvents({ limit: 200 })
  const completedCount = useMemo(
    () => events.filter((e) => e.event_type === 'evolution.completed').length,
    [events]
  )
  const lastSeenRef = useRef(0)

  const load = async () => {
    try {
      const [metrics, executions, evoHistory] = await Promise.all([
        fetchDashboardMetrics(EXEC_LIMIT),
        fetchRecentExecutions(EXEC_LIMIT),
        fetchEvolutionHistory(undefined, 500),
      ])
      const indexMap = buildExecutionIndexMap(executions)
      const eventGroups = groupEventsByExecution(evoHistory.events, indexMap)
      const merged = mergeData(
        metrics.improvement_trends.success_rate_trend,
        eventGroups
      )
      setData(merged)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load correlation data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    void load()
  }, [])

  // Refresh when a new evolution.completed event arrives.
  useEffect(() => {
    if (completedCount === lastSeenRef.current) return
    lastSeenRef.current = completedCount
    void load()
  }, [completedCount])

  // Summary stats
  const totalPromptBumps = data.filter((d) => d.hasPromptBump).length
  const totalSkillBumps = data.filter((d) => d.hasSkillBump).length
  const totalTopoChanges = data.filter((d) => d.hasTopologyChange).length
  const maxVersions = Math.max(
    ...data.map((d) => Math.max(d.promptVersions, d.skillVersions)),
    1
  )

  // Reference dots for topology changes on the pass-rate line.
  const topologyDots = data.filter((d) => d.hasTopologyChange)

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-12" />
        <Skeleton className="h-[350px]" />
      </div>
    )
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base text-destructive">Failed to load</CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">No execution data yet</CardTitle>
          <CardDescription>
            Run several executions with the evolution loop enabled — the chart populates
            automatically as metrics and version bumps accumulate.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">
          Pass-Rate vs. Evolution Events
        </CardTitle>
        <CardDescription>
          Thesis-defense figure — correlates autonomous learning with measurable
          performance improvement across executions.
        </CardDescription>
        <div className="flex flex-wrap gap-2 pt-2">
          {totalPromptBumps > 0 && (
            <Badge variant="outline" className="gap-1 text-[11px]">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: '#6366f1' }}
              />
              {totalPromptBumps} prompt updates
            </Badge>
          )}
          {totalSkillBumps > 0 && (
            <Badge variant="outline" className="gap-1 text-[11px]">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: '#f59e0b' }}
              />
              {totalSkillBumps} skill rebuilds
            </Badge>
          )}
          {totalTopoChanges > 0 && (
            <Badge variant="outline" className="gap-1 text-[11px]">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: '#ef4444' }}
              />
              {totalTopoChanges} topology changes
            </Badge>
          )}
          <Badge variant="secondary" className="text-[11px]">
            {data.length} executions
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-[350px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={data}
              margin={{ top: 10, right: 30, left: 10, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="execution"
                tick={{ fontSize: 12 }}
                label={{
                  value: 'Execution #',
                  position: 'insideBottom',
                  offset: -5,
                  fontSize: 12,
                }}
              />
              <YAxis
                yAxisId="left"
                domain={[0, 100]}
                tick={{ fontSize: 12 }}
                label={{
                  value: 'Pass-Rate %',
                  angle: -90,
                  position: 'insideLeft',
                  fontSize: 12,
                }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                domain={[0, Math.ceil(maxVersions * 1.2)]}
                allowDecimals={false}
                tick={{ fontSize: 12 }}
                label={{
                  value: 'Cumulative versions',
                  angle: 90,
                  position: 'insideRight',
                  fontSize: 12,
                }}
              />
              <Tooltip
                content={<CorrelationTooltip />}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />

              {/* Pass-rate line (primary) */}
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="passRate"
                stroke="#22c55e"
                strokeWidth={2}
                dot={<EvolutionMarkerDot />}
                activeDot={{ r: 5, stroke: '#22c55e', strokeWidth: 2 }}
                name="Pass-Rate %"
              />

              {/* Cumulative prompt versions (stepped) */}
              <Line
                yAxisId="right"
                type="stepAfter"
                dataKey="promptVersions"
                stroke="#6366f1"
                strokeWidth={1.5}
                strokeDasharray="5 3"
                dot={<EvolutionMarkerDot />}
                activeDot={{ r: 5, stroke: '#6366f1', strokeWidth: 2 }}
                name="Prompt versions"
              />

              {/* Cumulative skill versions (stepped) */}
              <Line
                yAxisId="right"
                type="stepAfter"
                dataKey="skillVersions"
                stroke="#f59e0b"
                strokeWidth={1.5}
                strokeDasharray="5 3"
                dot={<EvolutionMarkerDot />}
                activeDot={{ r: 5, stroke: '#f59e0b', strokeWidth: 2 }}
                name="Skill versions"
              />

              {/* Topology-change reference dots on the pass-rate line */}
              {topologyDots.map((d) => (
                <ReferenceDot
                  key={`topo-${d.execution}`}
                  yAxisId="left"
                  x={d.execution}
                  y={d.passRate}
                  r={5}
                  fill="#ef4444"
                  stroke="#fff"
                  strokeWidth={1.5}
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
