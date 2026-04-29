'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { fetchEvalRuns, fetchEvalRun } from '@/lib/api'
import { TrendChart } from './trend-chart'
import type { EvalRunSummary, EvalRunDetail, EvalTaskProgress } from '@/types'

const STATUS_COLORS: Record<string, string> = {
  running: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

const TASK_STATUS_COLORS: Record<string, string> = {
  passed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  resolved: 'bg-red-100 text-red-700',
  error: 'bg-red-100 text-red-700',
  timeout: 'bg-amber-100 text-amber-700',
}

function PassBadge({ value }: { value: number }) {
  const pct = value * 100
  const color = pct >= 80 ? 'bg-green-100 text-green-700' :
                pct >= 50 ? 'bg-amber-100 text-amber-700' :
                'bg-red-100 text-red-700'
  return <Badge className={color}>{pct.toFixed(1)}%</Badge>
}

export function RunResultsList() {
  const [runs, setRuns] = useState<EvalRunSummary[]>([])
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [runDetail, setRunDetail] = useState<EvalRunDetail | null>(null)
  const [loading, setLoading] = useState(true)

  async function loadRuns() {
    try {
      const data = await fetchEvalRuns()
      setRuns(data)
    } catch {
      setRuns([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRuns()
    const interval = setInterval(loadRuns, 5000)
    return () => clearInterval(interval)
  }, [])

  async function toggleExpand(runId: string) {
    if (expandedRun === runId) {
      setExpandedRun(null)
      setRunDetail(null)
      return
    }
    try {
      const detail = await fetchEvalRun(runId)
      setRunDetail(detail)
      setExpandedRun(runId)
    } catch {
      // ignore
    }
  }

  return (
    <>
    <TrendChart runs={runs} />
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Run Results</CardTitle>
            <CardDescription>
              History of all benchmark runs with Pass@1 scores.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={loadRuns}>
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading runs...</p>
        ) : runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No benchmark runs yet. Start one from the &quot;Run Benchmark&quot; tab.</p>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <Collapsible
                key={run.run_id}
                open={expandedRun === run.run_id}
                onOpenChange={() => toggleExpand(run.run_id)}
              >
                <CollapsibleTrigger asChild>
                  <div className="flex items-center justify-between p-3 rounded border cursor-pointer hover:bg-accent/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <Badge className={STATUS_COLORS[run.status] || ''}>
                        {run.status}
                      </Badge>
                      <span className="font-medium text-sm">{run.suite}</span>
                      {run.ablation_mode && (
                        <Badge variant="outline">{run.ablation_mode}</Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-muted-foreground">
                        {run.tasks_passed}/{run.tasks_total} passed
                      </span>
                      <PassBadge value={run.pass_at_1} />
                      <span className="text-xs text-muted-foreground">
                        {new Date(run.started_at).toLocaleString()}
                      </span>
                    </div>
                  </div>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  {expandedRun === run.run_id && runDetail && (
                    <div className="mt-2 ml-4 space-y-1 border-l-2 pl-3">
                      <p className="text-xs text-muted-foreground mb-2">
                        Seed: {runDetail.seed}
                        {runDetail.total_tokens > 0 && (
                          <> &middot; Tokens: {runDetail.total_tokens.toLocaleString()}</>
                        )}
                        {runDetail.total_duration_ms > 0 && (
                          <> &middot; Dauer: {(runDetail.total_duration_ms / 1000).toFixed(1)}s</>
                        )}
                        {runDetail.completed_at && (
                          <> &middot; {new Date(runDetail.completed_at).toLocaleString()}</>
                        )}
                        {runDetail.error && (
                          <span className="text-red-600"> &middot; Error: {runDetail.error}</span>
                        )}
                      </p>
                      {(runDetail.task_results || []).map((tp, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between p-2 rounded text-sm bg-accent/30"
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs w-6 text-muted-foreground">
                              {idx + 1}
                            </span>
                            <span>{tp.task_id}</span>
                            <Badge variant="outline" className="text-xs">{tp.level}</Badge>
                          </div>
                          <div className="flex items-center gap-2">
                            {(tp.tokens_total ?? 0) > 0 && (
                              <span className="text-xs text-muted-foreground">
                                {tp.tokens_total!.toLocaleString()} tok
                              </span>
                            )}
                            {tp.duration_ms > 0 && (
                              <span className="text-xs text-muted-foreground">
                                {(tp.duration_ms / 1000).toFixed(1)}s
                              </span>
                            )}
                            <Badge className={TASK_STATUS_COLORS[tp.status] || ''}>
                              {tp.pass_result ? 'passed' : tp.status === 'resolved' ? 'failed' : tp.status}
                            </Badge>
                            {tp.error && (
                              <span className="text-xs text-red-500 max-w-48 truncate">
                                {tp.error}
                              </span>
                            )}
                          </div>
                          {((tp.missing_keywords?.length ?? 0) > 0 || (tp.missing_sections?.length ?? 0) > 0) && (
                            <div className="mt-1 text-xs text-muted-foreground col-span-full ml-8">
                              {(tp.missing_keywords?.length ?? 0) > 0 && (
                                <p><span className="text-red-500 font-medium">Missing keywords:</span> {tp.missing_keywords!.join(', ')}</p>
                              )}
                              {(tp.missing_sections?.length ?? 0) > 0 && (
                                <p><span className="text-red-500 font-medium">Missing sections:</span> {tp.missing_sections!.join(', ')}</p>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </CollapsibleContent>
              </Collapsible>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
    </>
  )
}
