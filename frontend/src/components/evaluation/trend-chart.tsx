'use client'

import { useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { EvalRunSummary } from '@/types'

interface TrendChartProps {
  runs: EvalRunSummary[]
}

export function TrendChart({ runs }: TrendChartProps) {
  const data = useMemo(() => {
    const completed = runs
      .filter((r) => r.status === 'completed' && r.started_at)
      .sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime())

    return completed.map((r, i) => ({
      index: i + 1,
      date: new Date(r.started_at).toLocaleDateString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      }),
      pass_at_1: Math.round(r.pass_at_1 * 1000) / 10,
      suite: r.suite,
      tasks: `${r.tasks_passed}/${r.tasks_total}`,
      run_id: r.run_id.slice(0, 8),
    }))
  }, [runs])

  if (data.length < 2) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Pass@1 Trend</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              className="text-muted-foreground"
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => `${v}%`}
              className="text-muted-foreground"
            />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const d = payload[0].payload
                return (
                  <div className="rounded border bg-background p-2 text-xs shadow-sm">
                    <p className="font-medium">{d.suite}</p>
                    <p>Pass@1: {d.pass_at_1}%</p>
                    <p>Tasks: {d.tasks}</p>
                    <p className="text-muted-foreground">{d.date}</p>
                  </div>
                )
              }}
            />
            <ReferenceLine y={80} stroke="#22c55e" strokeDasharray="3 3" />
            <Line
              type="monotone"
              dataKey="pass_at_1"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}