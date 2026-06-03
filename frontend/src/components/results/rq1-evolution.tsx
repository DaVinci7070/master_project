'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { RQ1 } from '@/data/thesis-results'
import { CHART, ChartTooltip, KpiCard, NoteBox, QuestionHeader, pct } from './shared'

function AblationCard({ pair }: { pair: (typeof RQ1.ablation)[number] }) {
  const data = [
    { name: 'Evolution AN', value: Math.round(pair.meanOn * 1000) / 10, fill: CHART.on },
    { name: 'Evolution AUS', value: Math.round(pair.meanOff * 1000) / 10, fill: CHART.off },
  ]
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-base">
          <span>{pair.tier}-Modell</span>
          <Badge variant="secondary" className="font-mono text-[10px]">
            {pair.model}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ResponsiveContainer width="100%" height={150}>
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
            <Tooltip content={<ChartTooltip formatter={(v) => `${v}%`} />} cursor={{ fill: 'rgba(148,163,184,0.1)' }} />
            <Bar dataKey="value" name="Ø Score" radius={[4, 4, 0, 0]} maxBarSize={64}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          <div>
            <p className="text-muted-foreground">Δ Pass@1</p>
            <p className="font-semibold text-green-600 tabular-nums">+{pct(pair.deltaPass)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">p-Wert</p>
            <p className="font-semibold tabular-nums">{pair.pValue.toFixed(3)}</p>
            <Badge className="mt-0.5 bg-green-100 text-green-700 text-[10px]">signifikant</Badge>
          </div>
          <div>
            <p className="text-muted-foreground">Effektstärke</p>
            <p className="font-semibold tabular-nums">{pair.effectSize.toFixed(2)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function PerLevelChart({
  title,
  data,
}: {
  title: string
  data: typeof RQ1.perLevelWeak
}) {
  const chartData = data.map((d) => ({
    level: d.level,
    AN: Math.round(d.on * 1000) / 10,
    AUS: Math.round(d.off * 1000) / 10,
  }))
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="level" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
            <Tooltip content={<ChartTooltip formatter={(v) => `${v}%`} />} cursor={{ fill: 'rgba(148,163,184,0.1)' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="AN" name="Evolution AN" fill={CHART.on} radius={[3, 3, 0, 0]} maxBarSize={40} />
            <Bar dataKey="AUS" name="Evolution AUS" fill={CHART.off} radius={[3, 3, 0, 0]} maxBarSize={40} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

export function Rq1Evolution() {
  const { capabilityTiers } = RQ1
  return (
    <div className="space-y-6">
      <QuestionHeader
        badge="RQ1 · Selbst-Evolution"
        question={RQ1.question}
        verdict={RQ1.verdict}
        summary={RQ1.summary}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Δ Pass@1 (Weak)" value={`+${pct(RQ1.ablation[0].deltaPass)}`} accent="good" hint="Evolution AN vs. AUS" />
        <KpiCard label="Δ Pass@1 (Strong)" value={`+${pct(RQ1.ablation[1].deltaPass)}`} accent="good" hint="Evolution AN vs. AUS" />
        <KpiCard label="Beide signifikant" value="p < 0.05" accent="good" hint="Wilcoxon, paired" />
        <KpiCard label="Größter Effekt" value="L5 (Audio)" hint="+33 pp bei Weak" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {RQ1.ablation.map((p) => (
          <AblationCard key={p.tier} pair={p} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <PerLevelChart title="Pass@1 je Komplexität — Weak-Modell" data={RQ1.perLevelWeak} />
        <PerLevelChart title="Pass@1 je Komplexität — Strong-Modell" data={RQ1.perLevelStrong} />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Modell-Stufen im Vergleich (Evolution aktiv)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            {capabilityTiers.tiers.map((t) => (
              <div key={t.tier} className="rounded-lg border p-3">
                <p className="text-sm font-medium">{t.tier}</p>
                <p className="font-mono text-[10px] text-muted-foreground">{t.model}</p>
                <p className="mt-2 text-xl font-semibold tabular-nums">{pct(t.meanScore)}</p>
                <p className="text-xs text-muted-foreground">Ø Score</p>
              </div>
            ))}
          </div>
          <NoteBox>{capabilityTiers.note}</NoteBox>
        </CardContent>
      </Card>
    </div>
  )
}
