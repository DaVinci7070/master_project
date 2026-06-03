'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { CheckCircle2, MinusCircle } from 'lucide-react'

export const CHART = {
  on: '#3b82f6', // primär / "AN" / Warm / Kombiniert
  off: '#94a3b8', // neutral / "AUS" / Cold
  good: '#22c55e',
  warn: '#f59e0b',
  bad: '#ef4444',
  grid: 'rgba(148,163,184,0.25)',
}

export function pct(v: number, digits = 1): string {
  return `${(v * 100).toFixed(digits)}%`
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const ok = verdict === 'bestätigt'
  return (
    <Badge
      className={
        ok ? 'bg-green-100 text-green-700 gap-1' : 'bg-amber-100 text-amber-700 gap-1'
      }
    >
      {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <MinusCircle className="h-3.5 w-3.5" />}
      {ok ? 'Bestätigt' : 'Teilweise'}
    </Badge>
  )
}

export function QuestionHeader({
  badge,
  question,
  verdict,
  summary,
}: {
  badge: string
  question: string
  verdict: string
  summary: string
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant="secondary" className="text-xs font-mono">
          {badge}
        </Badge>
        <VerdictBadge verdict={verdict} />
      </div>
      <h2 className="text-lg font-semibold leading-snug">{question}</h2>
      <p className="text-sm text-muted-foreground max-w-3xl leading-relaxed">{summary}</p>
    </div>
  )
}

export function KpiCard({
  label,
  value,
  hint,
  accent,
}: {
  label: string
  value: string
  hint?: string
  accent?: 'good' | 'warn' | 'neutral'
}) {
  const color =
    accent === 'good'
      ? 'text-green-600'
      : accent === 'warn'
        ? 'text-amber-600'
        : 'text-foreground'
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  )
}

export function NoteBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed bg-muted/30 p-3 text-xs text-muted-foreground leading-relaxed">
      {children}
    </div>
  )
}

export function ChartTooltip({
  active,
  payload,
  label,
  formatter,
}: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: string
  formatter?: (v: number) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border bg-background p-2 text-xs shadow-sm">
      {label && <p className="mb-1 font-medium">{label}</p>}
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-medium tabular-nums">
            {formatter ? formatter(p.value) : p.value}
          </span>
        </p>
      ))}
    </div>
  )
}
