'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface ExecutionSummaryProps {
  executionId: string
  status: 'complete' | 'error'
  startedAt: string
  completedAt: string
  agentsRun: number
  totalDuration: number
  tokensUsed: number
  result?: Record<string, unknown>
  error?: string
}

export function ExecutionSummary({
  executionId,
  status,
  startedAt,
  completedAt,
  agentsRun,
  totalDuration,
  tokensUsed,
  result,
  error,
}: ExecutionSummaryProps) {
  return (
    <Card className={status === 'error' ? 'border-red-200' : 'border-green-200'}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Execution Summary</CardTitle>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
            status === 'complete'
              ? 'bg-green-100 text-green-700'
              : 'bg-red-100 text-red-700'
          }`}>
            {status === 'complete' ? 'Completed' : 'Failed'}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Key metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-sm text-gray-500">Duration</p>
            <p className="font-semibold">{(totalDuration / 1000).toFixed(1)}s</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Agents Run</p>
            <p className="font-semibold">{agentsRun}</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Tokens Used</p>
            <p className="font-semibold">{tokensUsed.toLocaleString()}</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Execution ID</p>
            <p className="font-mono text-xs">{executionId.slice(0, 8)}</p>
          </div>
        </div>

        {/* Time range */}
        <div className="text-sm text-gray-500">
          <span>{new Date(startedAt).toLocaleString()}</span>
          <span className="mx-2">→</span>
          <span>{new Date(completedAt).toLocaleString()}</span>
        </div>

        {/* Error message if failed */}
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}

        {/* Result preview if successful */}
        {result && (
          <div>
            <p className="text-sm text-gray-500 mb-2">Result Preview</p>
            <pre className="bg-gray-100 p-3 rounded-lg text-xs overflow-x-auto">
              {JSON.stringify(result, null, 2).slice(0, 500)}
              {JSON.stringify(result).length > 500 && '...'}
            </pre>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
