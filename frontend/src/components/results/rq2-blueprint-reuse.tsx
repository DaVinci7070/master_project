'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { RQ2 } from '@/data/thesis-results'
import { CHART, ChartTooltip, KpiCard, NoteBox, QuestionHeader, pct } from './shared'

function fmtTokens(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v}`
}

export function Rq2BlueprintReuse() {
  const assemblySaving =
    (RQ2.metrics[1].cold - RQ2.metrics[1].warm) / RQ2.metrics[1].cold
  const passDelta = RQ2.metrics[0].warm - RQ2.metrics[0].cold

  const tokenData = RQ2.tokenBreakdown.map((t) => ({
    phase: t.phase,
    Cold: Math.round(t.cold / 1000),
    Warm: Math.round(t.warm / 1000),
  }))

  const seedData = RQ2.perSeed.map((s) => ({
    seed: `Seed ${s.seed}`,
    Cold: Math.round(s.cold * 1000) / 10,
    Warm: Math.round(s.warm * 1000) / 10,
  }))

  return (
    <div className="space-y-6">
      <QuestionHeader
        badge="RQ2 · Blueprint-Reuse"
        question={RQ2.question}
        verdict={RQ2.verdict}
        summary={RQ2.summary}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Assembly-Tokens gespart"
          value={`−${pct(assemblySaving, 0)}`}
          accent="good"
          hint="Warm vs. Cold, pro Seed"
        />
        <KpiCard label="Pass@1 Warm" value={pct(RQ2.metrics[0].warm)} accent="good" hint={`+${pct(passDelta)} vs. Cold`} />
        <KpiCard label="Assembly-Anteil" value={`${RQ2.metrics[2].warm}%`} hint={`Cold: ${RQ2.metrics[2].cold}%`} />
        <KpiCard label="Setup" value={`${RQ2.seeds} Seeds`} hint={`${RQ2.tasksPerSeed} Tasks / Seed`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Token-Verbrauch je Phase (Cold vs. Warm)</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={tokenData} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="phase" tick={{ fontSize: 10 }} interval={0} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}k`} />
                <Tooltip content={<ChartTooltip formatter={(v) => `${v}k Tokens`} />} cursor={{ fill: 'rgba(148,163,184,0.1)' }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="Cold" fill={CHART.off} radius={[3, 3, 0, 0]} maxBarSize={48} />
                <Bar dataKey="Warm" fill={CHART.on} radius={[3, 3, 0, 0]} maxBarSize={48} />
              </BarChart>
            </ResponsiveContainer>
            <p className="mt-2 text-xs text-muted-foreground">
              Die Build-Phase (Assembly) schrumpft beim Warm-Start von {fmtTokens(RQ2.tokenBreakdown[0].cold)} auf{' '}
              {fmtTokens(RQ2.tokenBreakdown[0].warm)} Tokens — Blueprints werden wiederverwendet statt neu gebaut.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Pass@1 je Seed</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={seedData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="seed" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                <Tooltip content={<ChartTooltip formatter={(v) => `${v}%`} />} cursor={{ fill: 'rgba(148,163,184,0.1)' }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="Cold" fill={CHART.off} radius={[3, 3, 0, 0]} maxBarSize={40} />
                <Bar dataKey="Warm" fill={CHART.on} radius={[3, 3, 0, 0]} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
            <p className="mt-2 text-xs text-muted-foreground">
              Warm-Start erreicht in 2 von 3 Seeds eine höhere Task-Completion als Cold-Start.
            </p>
          </CardContent>
        </Card>
      </div>

      <NoteBox>{RQ2.note}</NoteBox>
    </div>
  )
}
