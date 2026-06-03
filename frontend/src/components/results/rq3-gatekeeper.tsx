'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { RQ3 } from '@/data/thesis-results'
import { CHART, ChartTooltip, KpiCard, NoteBox, QuestionHeader, pct } from './shared'

const LAYER_COLOR: Record<string, string> = {
  ast_only: CHART.off,
  alignment_only: '#a78bfa',
  combined: CHART.on,
}

export function Rq3Gatekeeper() {
  const combined = RQ3.layers.find((l) => l.id === 'combined')!

  const metricData = (['accuracy', 'precision', 'recall', 'f1'] as const).map((m) => {
    const label = { accuracy: 'Accuracy', precision: 'Precision', recall: 'Recall', f1: 'F1' }[m]
    const row: Record<string, string | number> = { metric: label }
    for (const layer of RQ3.layers) {
      row[layer.label] = Math.round(layer[m] * 1000) / 10
    }
    return row
  })

  const sweepData = RQ3.thresholdSweep.map((s) => ({
    threshold: s.threshold,
    TPR: Math.round(s.tpr * 1000) / 10,
    FPR: Math.round(s.fpr * 1000) / 10,
    F1: Math.round(s.f1 * 1000) / 10,
  }))

  return (
    <div className="space-y-6">
      <QuestionHeader
        badge="RQ3 · Gatekeeper"
        question={RQ3.question}
        verdict={RQ3.verdict}
        summary={RQ3.summary}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="F1 (kombiniert)" value={pct(combined.f1)} accent="good" />
        <KpiCard label="Recall (kombiniert)" value={pct(combined.recall)} accent="good" hint="erkannte Gefahren" />
        <KpiCard label="Accuracy" value={pct(combined.accuracy)} accent="good" />
        <KpiCard label="Korpus" value={`${RQ3.corpusSize} Paare`} hint={`${RQ3.nRuns} Runs gemittelt`} />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Schicht-Vergleich: AST · Alignment · Kombiniert</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={metricData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="metric" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip content={<ChartTooltip formatter={(v) => `${v}%`} />} cursor={{ fill: 'rgba(148,163,184,0.1)' }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {RQ3.layers.map((l) => (
                <Bar key={l.id} dataKey={l.label} fill={LAYER_COLOR[l.id]} radius={[3, 3, 0, 0]} maxBarSize={28} />
              ))}
            </BarChart>
          </ResponsiveContainer>
          <p className="mt-2 text-xs text-muted-foreground">
            Reine AST-Analyse ist perfekt präzise (0 % Fehlalarme), erkennt aber nur {pct(RQ3.layers[0].recall, 0)} der
            Gefahren. Das semantische Alignment hebt den Recall auf {pct(combined.recall, 0)}.
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Erkennung je Kategorie</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-2 font-medium">Kategorie</th>
                    <th className="py-2 px-2 font-medium text-center">n</th>
                    <th className="py-2 px-2 font-medium text-center">Nur AST</th>
                    <th className="py-2 pl-2 font-medium text-center">Kombiniert</th>
                  </tr>
                </thead>
                <tbody>
                  {RQ3.categories.map((c) => (
                    <tr key={c.category} className="border-b last:border-0">
                      <td className="py-2 pr-2">{c.label}</td>
                      <td className="py-2 px-2 text-center tabular-nums text-muted-foreground">{c.n}</td>
                      <td className="py-2 px-2 text-center tabular-nums font-mono">{c.astCorrect}</td>
                      <td className="py-2 pl-2 text-center tabular-nums font-mono font-medium">{c.combinedCorrect}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Bypass-, Täuschungs- und semantische Fälle bleiben für die AST-Schicht unsichtbar (0/5) — erst die
              Kombination deckt sie auf.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Threshold-Sweep (kombiniert)</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={sweepData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                <XAxis dataKey="threshold" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                <Tooltip content={<ChartTooltip formatter={(v) => `${v}%`} />} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="TPR" name="True-Positive-Rate" stroke={CHART.good} strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="FPR" name="False-Positive-Rate" stroke={CHART.bad} strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="F1" name="F1" stroke={CHART.on} strokeWidth={2} strokeDasharray="4 2" dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
            <p className="mt-2 text-xs text-muted-foreground">
              Bei Schwelle 0.7 liegt das beste F1 (≈88 %) — hohe Erkennung bei vertretbarer Fehlalarmrate.
            </p>
          </CardContent>
        </Card>
      </div>

      <NoteBox>{RQ3.note}</NoteBox>
    </div>
  )
}
