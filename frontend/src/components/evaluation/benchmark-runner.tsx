'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  fetchSuites,
  fetchAblationModes,
  startBenchmarkRun,
} from '@/lib/api'
import { useEvalRunStream } from '@/hooks/useEvalRunStream'
import type { SuiteInfo, AblationModes, EvalTaskProgress } from '@/types'

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-600',
  running: 'bg-blue-100 text-blue-700',
  passed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  error: 'bg-red-100 text-red-700',
  timeout: 'bg-amber-100 text-amber-700',
}

export function BenchmarkRunner() {
  const [suites, setSuites] = useState<SuiteInfo[]>([])
  const [modes, setModes] = useState<AblationModes>({})
  const [selectedSuite, setSelectedSuite] = useState('')
  const [selectedMode, setSelectedMode] = useState<string>('')
  const [seed, setSeed] = useState(1)
  const [timeout, setTimeout] = useState(300)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const {
    taskProgress,
    tasksCompleted,
    tasksTotal,
    passAt1,
    runStatus,
    isConnected,
    startStream,
    reset,
  } = useEvalRunStream()

  useEffect(() => {
    fetchSuites().then(setSuites).catch(() => {})
    fetchAblationModes().then(setModes).catch(() => {})
  }, [])

  useEffect(() => {
    if (suites.length > 0 && !selectedSuite) {
      setSelectedSuite(suites[0].name)
    }
  }, [suites, selectedSuite])

  async function handleStart() {
    setStarting(true)
    setError(null)
    try {
      const suite = suites.find((s) => s.name === selectedSuite)
      const taskCount = suite?.task_count || 0

      const initialTasks: EvalTaskProgress[] = Array.from({ length: taskCount }, (_, i) => ({
        task_id: `task_${i}`,
        level: '',
        status: 'pending' as const,
        duration_ms: 0,
        pass_result: null,
        error: null,
      }))

      const response = await startBenchmarkRun({
        suite: selectedSuite,
        ablation_mode: selectedMode || null,
        seed,
        timeout,
      })

      startStream(response.run_id, initialTasks)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start run')
    } finally {
      setStarting(false)
    }
  }

  const isRunning = runStatus === 'running'
  const progressPct = tasksTotal > 0 ? Math.round((tasksCompleted / tasksTotal) * 100) : 0

  return (
    <div className="space-y-4">
      {/* Config */}
      <Card>
        <CardHeader>
          <CardTitle>Run Configuration</CardTitle>
          <CardDescription>
            Select a test suite, ablation mode, and parameters to start a benchmark run.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="suite">Test Suite</Label>
              <select
                id="suite"
                value={selectedSuite}
                onChange={(e) => setSelectedSuite(e.target.value)}
                disabled={isRunning}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {suites.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name} ({s.task_count} tasks)
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="mode">Ablation Mode</Label>
              <select
                id="mode"
                value={selectedMode}
                onChange={(e) => setSelectedMode(e.target.value)}
                disabled={isRunning}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">None (use current settings)</option>
                {Object.keys(modes).map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="seed">Seed</Label>
              <Input
                id="seed"
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                disabled={isRunning}
                min={1}
              />
            </div>
            <div>
              <Label htmlFor="timeout">Timeout (seconds)</Label>
              <Input
                id="timeout"
                type="number"
                value={timeout}
                onChange={(e) => setTimeout(Number(e.target.value))}
                disabled={isRunning}
                min={30}
                max={600}
              />
            </div>
          </div>

          {selectedMode && modes[selectedMode] && (
            <div className="flex gap-2 flex-wrap">
              {Object.entries(modes[selectedMode]).map(([flag, val]) => (
                <Badge key={flag} variant={val === 'true' ? 'default' : 'secondary'}>
                  {flag.replace('_ENABLED', '').toLowerCase()}: {val}
                </Badge>
              ))}
            </div>
          )}

          <div className="flex gap-2">
            <Button
              onClick={handleStart}
              disabled={starting || isRunning || !selectedSuite}
              className="flex-1"
            >
              {starting ? 'Starting...' : isRunning ? 'Running...' : 'Start Benchmark Run'}
            </Button>
            {(runStatus === 'completed' || runStatus === 'failed') && (
              <Button variant="outline" onClick={reset}>
                New Run
              </Button>
            )}
          </div>

          {error && (
            <div className="p-3 rounded-lg text-sm bg-red-50 text-red-700">{error}</div>
          )}
        </CardContent>
      </Card>

      {/* Live Progress */}
      {runStatus !== 'idle' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                Progress
                {isConnected && isRunning && (
                  <span className="ml-2 inline-block h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                )}
              </CardTitle>
              <div className="flex items-center gap-2">
                <Badge variant={runStatus === 'completed' ? 'default' : runStatus === 'failed' ? 'destructive' : 'secondary'}>
                  {runStatus}
                </Badge>
                <span className="text-sm text-muted-foreground">
                  {tasksCompleted}/{tasksTotal}
                </span>
                <Badge variant="outline">
                  Pass@1: {(passAt1 * 100).toFixed(1)}%
                </Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Progress bar */}
            <div className="w-full bg-gray-100 rounded-full h-2">
              <div
                className="bg-primary h-2 rounded-full transition-all duration-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>

            {/* Task list */}
            <div className="space-y-1 max-h-80 overflow-y-auto">
              {taskProgress.map((tp, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 rounded text-sm border"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs w-6 text-muted-foreground">{idx + 1}</span>
                    <span>{tp.task_id}</span>
                    {tp.level && (
                      <Badge variant="outline" className="text-xs">{tp.level}</Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {tp.duration_ms > 0 && (
                      <span className="text-xs text-muted-foreground">
                        {(tp.duration_ms / 1000).toFixed(1)}s
                      </span>
                    )}
                    <Badge className={STATUS_COLORS[tp.status] || ''}>
                      {tp.status}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
