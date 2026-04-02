'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'
import {
  ExecutionTimeline,
  ExecutionLogs,
  ExecutionSummary,
  ErrorModal,
} from '@/components/execution'
import { SharedMemoryView } from '@/components/execution/shared-memory-view'
import { ExecutionTimelineGraph, type TimelineAgent, type AgentStatus } from '@/components/execution/execution-timeline-graph'
import { useExecutionStatus } from '@/hooks'
import { fetchChallengeStatus } from '@/lib/api'
import type { ChallengeResultsResponse } from '@/types'

interface LogEntry {
  timestamp: string
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
  agentId?: string
}

interface AgentResult {
  agentId: string
  agentName: string
  success: boolean
  output?: string
  resultText?: string  // Extracted result text for display
  error?: string
  tokens?: number
  latencyMs?: number
}

export default function ExecutionDetailPage() {
  const params = useParams()
  const executionId = params.id as string

  const [logs, setLogs] = useState<LogEntry[]>([])
  const [showErrorModal, setShowErrorModal] = useState(false)
  const [executionError, setExecutionError] = useState<string | null>(null)
  const [isComplete, setIsComplete] = useState(false)
  const [startTime, setStartTime] = useState<string | null>(null)
  const [endTime, setEndTime] = useState<string | null>(null)
  const [agentResults, setAgentResults] = useState<AgentResult[]>([])
  const [totalTokens, setTotalTokens] = useState(0)
  const [challengeStatus, setChallengeStatus] = useState<string>('executing')

  // Timeline graph state
  const [timelineAgents, setTimelineAgents] = useState<TimelineAgent[]>([])
  const [currentAgentId, setCurrentAgentId] = useState<string | undefined>()

  const { data: event, isConnected } = useExecutionStatus(executionId)

  // Poll for challenge status updates
  const pollStatus = useCallback(async () => {
    try {
      // Find challenge by execution_id - poll the status endpoint
      const response = await fetch(`/api/backend/challenges/by-execution/${executionId}`)
      if (response.ok) {
        const data = await response.json()
        if (data) {
          // Update status from challenge data
          if (data.status) {
            setChallengeStatus(data.status)
          }

          // Check completion: status is resolved/failed OR execution_results exists with success
          const isCompleted = data.status === 'resolved' ||
                              data.status === 'failed' ||
                              (data.execution_results && data.execution_results.success === true)

          if (isCompleted && !isComplete) {
            console.log('Execution completed, updating view with results...')

            // Batch all state updates
            const newStartTime = data.created_at || new Date().toISOString()
            const newEndTime = data.updated_at || new Date().toISOString()

            setStartTime(newStartTime)
            setEndTime(newEndTime)
            setChallengeStatus(data.status || 'resolved')

            // Extract results if available
            if (data.execution_results) {
              const results = data.execution_results
              if (results.results) {
                // Parse wave results into agent results
                const parsed: AgentResult[] = []
                for (const [waveKey, waveData] of Object.entries(results.results as Record<string, Record<string, unknown>>)) {
                  for (const [agentKey, agentData] of Object.entries(waveData)) {
                    const ad = agentData as Record<string, unknown>
                    // Agent returned data = success (no explicit success field in output)
                    // Check if it's an error response or actual output
                    const isError = ad.error !== undefined

                    // Extract human-readable result text
                    let resultText = ''
                    if (ad.final_report && typeof ad.final_report === 'string') {
                      resultText = ad.final_report
                    } else if (ad.result && typeof ad.result === 'string') {
                      resultText = ad.result
                    } else if (ad.summary && typeof ad.summary === 'string') {
                      resultText = ad.summary
                    } else if (ad.report && typeof ad.report === 'string') {
                      resultText = ad.report
                    }

                    parsed.push({
                      // agentKey is now the agent name (e.g., "Summarizer Agent")
                      agentId: (ad.agent_id as string) || agentKey,
                      agentName: (ad.agent_name as string) || agentKey,
                      success: !isError,
                      output: JSON.stringify(ad, null, 2),
                      resultText,
                      error: ad.error as string,
                      tokens: ad.tokens_total as number,
                      latencyMs: ad.latency_ms as number,
                    })
                  }
                }
                setAgentResults(parsed)

                // Also update timeline agents from results
                const timelineFromResults: TimelineAgent[] = []
                let waveIndex = 1
                for (const [waveKey, waveData] of Object.entries(results.results as Record<string, Record<string, unknown>>)) {
                  for (const [agentKey, agentData] of Object.entries(waveData)) {
                    const ad = agentData as Record<string, unknown>
                    const isError = ad.error !== undefined
                    timelineFromResults.push({
                      id: (ad.agent_id as string) || agentKey,
                      name: (ad.agent_name as string) || agentKey,
                      wave: waveIndex,
                      status: isError ? 'failed' : 'completed',
                      durationMs: ad.latency_ms as number,
                    })
                  }
                  waveIndex++
                }
                setTimelineAgents(timelineFromResults)
              }

              if (results.error) {
                setExecutionError(results.error as string)
                setShowErrorModal(true)
              }
            }

            // Set isComplete LAST to trigger UI update after all data is ready
            setIsComplete(true)
            console.log('View update complete - isComplete set to true')
          }
        }
      }
    } catch (err) {
      console.error('Failed to poll status:', err)
    }
  }, [executionId, isComplete])

  // Poll every second while executing
  useEffect(() => {
    // Always do initial poll immediately
    pollStatus()

    if (isComplete) return

    // Poll every second for faster updates
    const interval = setInterval(pollStatus, 1000)

    return () => clearInterval(interval)
  }, [isComplete, pollStatus])

  useEffect(() => {
    if (!event) return

    // Track start time
    if (event.type === 'start' && !startTime) {
      setStartTime(event.timestamp)
    }

    // Add log entry
    setLogs((prev) => [
      ...prev,
      {
        timestamp: event.timestamp,
        level: event.type === 'error' ? 'error' : 'info',
        message: event.type === 'error' ? event.error || 'Unknown error' : `${event.type}: ${event.agent_id}`,
        agentId: event.agent_id,
      },
    ])

    // Update timeline agents based on event type
    if (event.agent_id) {
      const agentId = event.agent_id // Capture for closure - TypeScript now knows it's string
      const agentName = event.agent_name || agentId
      const waveNum = event.wave || 1

      setTimelineAgents((prev) => {
        const existing = prev.find(a => a.id === agentId)

        if (event.type === 'agent_start') {
          // Agent starting - add or update
          setCurrentAgentId(agentId)
          if (existing) {
            return prev.map(a =>
              a.id === agentId
                ? { ...a, status: 'running' as AgentStatus, startedAt: event.timestamp }
                : a
            )
          } else {
            return [
              ...prev,
              {
                id: agentId,
                name: agentName,
                wave: waveNum,
                status: 'running' as AgentStatus,
                startedAt: event.timestamp,
              },
            ]
          }
        } else if (event.type === 'agent_complete') {
          // Agent completed
          const startedAt = existing?.startedAt
          const durationMs = startedAt
            ? new Date(event.timestamp).getTime() - new Date(startedAt).getTime()
            : undefined

          return prev.map(a =>
            a.id === agentId
              ? {
                  ...a,
                  status: 'completed' as AgentStatus,
                  completedAt: event.timestamp,
                  durationMs,
                }
              : a
          )
        } else if (event.type === 'agent_error') {
          // Agent failed
          return prev.map(a =>
            a.id === agentId
              ? { ...a, status: 'failed' as AgentStatus, completedAt: event.timestamp }
              : a
          )
        }

        return prev
      })
    }

    // Handle completion
    if (event.type === 'complete') {
      setIsComplete(true)
      setEndTime(event.timestamp)
      setCurrentAgentId(undefined)
    }

    // Handle error - show modal per CONTEXT
    if (event.type === 'error') {
      setExecutionError(event.error || 'Unknown error')
      setShowErrorModal(true)
      setEndTime(event.timestamp)
    }
  }, [event, startTime])

  function handleRetry() {
    setShowErrorModal(false)
    // TODO: Implement retry logic
    window.location.href = '/execution'
  }

  function handleViewLogs() {
    setShowErrorModal(false)
    // Logs are already visible on page
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Execution Details</h1>
          <p className="text-gray-500 mt-1 font-mono text-sm">{executionId}</p>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={() => pollStatus()}
            className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
            title="Refresh status"
          >
            ↻ Refresh
          </button>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
            challengeStatus === 'resolved' ? 'bg-green-100 text-green-700' :
            challengeStatus === 'failed' ? 'bg-red-100 text-red-700' :
            challengeStatus === 'executing' ? 'bg-blue-100 text-blue-700' :
            'bg-gray-100 text-gray-700'
          }`}>
            {challengeStatus === 'resolved' ? 'Completed' :
             challengeStatus === 'failed' ? 'Failed' :
             challengeStatus === 'executing' ? 'Executing...' :
             challengeStatus}
          </span>
          <span className={`text-sm ${isConnected ? 'text-green-600' : 'text-gray-400'}`}>
            {isConnected ? '● Live updates' : '○ Not connected'}
          </span>
        </div>
      </div>

      {/* Horizontal Timeline Graph - Auto-scrolling agent progress */}
      <ExecutionTimelineGraph
        agents={timelineAgents}
        currentAgentId={currentAgentId}
      />

      {/* Vertical Timeline */}
      <ExecutionTimeline executionId={executionId} />

      {/* Logs (collapsed by default per CONTEXT) */}
      <ExecutionLogs logs={logs} />

      {/* Summary (shows on completion per CONTEXT) */}
      {(isComplete || executionError) && startTime && endTime && (
        <ExecutionSummary
          executionId={executionId}
          status={executionError ? 'error' : 'complete'}
          startedAt={startTime}
          completedAt={endTime}
          agentsRun={agentResults.length || logs.filter(l => l.level === 'info').length}
          totalDuration={new Date(endTime).getTime() - new Date(startTime).getTime()}
          tokensUsed={totalTokens || agentResults.reduce((sum, r) => sum + (r.tokens || 0), 0)}
          error={executionError || undefined}
        />
      )}

      {/* Shared Memory View (shows on completion) */}
      {isComplete && <SharedMemoryView executionId={executionId} />}

      {/* Final Report - Prominent Display */}
      {isComplete && agentResults.length > 0 && (() => {
        // Find report finalizer or summarizer by name pattern
        const summarizerResult = agentResults.find(r =>
          r.agentName.toLowerCase().includes('report_finalizer') ||
          r.agentName.toLowerCase().includes('finalizer') ||
          r.agentName.toLowerCase().includes('summarizer') ||
          r.agentName.toLowerCase().includes('zusammenfassung')
        )
        const reportText = summarizerResult?.resultText || ''

        return (
          <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border-2 border-blue-300 p-8 shadow-lg">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-12 h-12 bg-blue-500 rounded-full flex items-center justify-center">
                <span className="text-2xl">📋</span>
              </div>
              <div>
                <h2 className="text-2xl font-bold text-blue-900">Analyseergebnis</h2>
                <p className="text-blue-600 text-sm">Generiert von {summarizerResult?.agentName || 'Summarizer Agent'}</p>
              </div>
            </div>
            <div className="bg-white rounded-lg p-6 shadow-inner border border-blue-100">
              {reportText ? (
                <div className="prose prose-lg max-w-none">
                  <pre className="whitespace-pre-wrap font-sans text-gray-800 leading-relaxed">
                    {reportText}
                  </pre>
                </div>
              ) : (
                <p className="text-gray-500 italic">Kein Bericht verfügbar. Prüfen Sie die Agent-Details unten.</p>
              )}
            </div>
          </div>
        )
      })()}

      {/* Agent Results (shows on completion) */}
      {isComplete && agentResults.length > 0 && (
        <details className="bg-white rounded-lg border" open>
          <summary className="p-6 cursor-pointer hover:bg-gray-50 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Agent-Ergebnisse ({agentResults.length} Agents)</h2>
            <span className="text-sm text-gray-500">Klicken zum Ein-/Ausklappen</span>
          </summary>
          <div className="p-6 pt-0 space-y-4">
            {agentResults.map((result, idx) => (
              <div
                key={idx}
                className={`p-4 rounded-lg border ${
                  result.success ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="font-semibold text-gray-900">{result.agentName}</span>
                    <span className="text-xs text-gray-400 ml-2">({result.agentId.slice(0, 8)}...)</span>
                  </div>
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    result.success ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}>
                    {result.success ? '✓ Erfolg' : '✗ Fehler'}
                  </span>
                </div>
                {/* Show result text prominently if available */}
                {result.resultText && (
                  <div className="mt-3 p-3 bg-white rounded border text-sm text-gray-700">
                    <pre className="whitespace-pre-wrap font-sans">{result.resultText}</pre>
                  </div>
                )}
                {result.output && !result.resultText && (
                  <details className="mt-2">
                    <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-700">
                      Raw Output anzeigen
                    </summary>
                    <pre className="text-xs bg-gray-50 p-2 rounded overflow-x-auto mt-2 max-h-48 overflow-y-auto">
                      {result.output}
                    </pre>
                  </details>
                )}
                {result.error && (
                  <p className="text-sm text-red-600 mt-2 font-medium">{result.error}</p>
                )}
                <div className="flex gap-4 mt-2 text-xs text-gray-500">
                  {result.tokens !== undefined && <span>Tokens: {result.tokens}</span>}
                  {result.latencyMs !== undefined && <span>Latency: {result.latencyMs}ms</span>}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Error modal interrupt per CONTEXT */}
      {executionError && (
        <ErrorModal
          open={showErrorModal}
          onOpenChange={setShowErrorModal}
          error={executionError}
          executionId={executionId}
          onRetry={handleRetry}
          onViewLogs={handleViewLogs}
          onDismiss={() => setShowErrorModal(false)}
        />
      )}
    </div>
  )
}
