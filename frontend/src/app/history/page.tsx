'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
} from 'lucide-react'

interface ExecutionSummary {
  id: string
  challenge_id: string | null
  project_id: string
  status: string
  agents_executed: number
  waves_executed: number
  duration_ms: number | null
  error: string | null
  started_at: string
  completed_at: string | null
}

interface ExecutionsResponse {
  executions: ExecutionSummary[]
  total: number
  limit: number
  offset: number
}

export default function HistoryPage() {
  const [data, setData] = useState<ExecutionsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const pageSize = 20

  const fetchExecutions = async (offset: number = 0) => {
    try {
      setLoading(true)
      const response = await fetch(
        `/api/backend/executions?limit=${pageSize}&offset=${offset}`
      )
      if (!response.ok) {
        throw new Error('Failed to fetch executions')
      }
      const result = await response.json()
      setData(result)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchExecutions(page * pageSize)
  }, [page])

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-green-500" />
      case 'failed':
        return <XCircle className="w-5 h-5 text-red-500" />
      case 'running':
        return <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
      default:
        return <Clock className="w-5 h-5 text-gray-400" />
    }
  }

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      completed: 'bg-green-100 text-green-700',
      failed: 'bg-red-100 text-red-700',
      running: 'bg-blue-100 text-blue-700',
      pending: 'bg-gray-100 text-gray-700',
    }
    return styles[status] || 'bg-gray-100 text-gray-700'
  }

  const formatDuration = (ms: number | null) => {
    if (ms === null) return '-'
    if (ms < 1000) return `${ms}ms`
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
    return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Execution History</h1>
          <p className="text-gray-500 mt-1">
            Alle vergangenen Ausführungen
          </p>
        </div>
        <button
          onClick={() => fetchExecutions(page * pageSize)}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Aktualisieren
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="bg-white rounded-lg border p-12 flex items-center justify-center">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
        </div>
      ) : data && data.executions.length === 0 ? (
        <div className="bg-white rounded-lg border p-12 text-center">
          <Clock className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <h2 className="text-lg font-medium text-gray-700">
            Keine Executions gefunden
          </h2>
          <p className="text-gray-500 mt-2">
            Starten Sie eine Challenge-Ausführung, um hier die Historie zu sehen.
          </p>
        </div>
      ) : (
        <>
          {/* Table */}
          <div className="bg-white rounded-lg border overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                    Status
                  </th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                    Execution ID
                  </th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                    Gestartet
                  </th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                    Dauer
                  </th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                    Agents
                  </th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                    Waves
                  </th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                    Projekt
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {data?.executions.map((execution) => (
                  <tr
                    key={execution.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        {getStatusIcon(execution.status)}
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium ${getStatusBadge(
                            execution.status
                          )}`}
                        >
                          {execution.status}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <Link
                        href={`/execution/${execution.id}`}
                        className="font-mono text-sm text-blue-600 hover:underline"
                      >
                        {execution.id.slice(0, 8)}...
                      </Link>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {formatDate(execution.started_at)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {formatDuration(execution.duration_ms)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {execution.agents_executed}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {execution.waves_executed}
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-xs bg-gray-100 px-2 py-1 rounded">
                        {execution.project_id}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Zeige {page * pageSize + 1} -{' '}
                {Math.min((page + 1) * pageSize, data?.total || 0)} von{' '}
                {data?.total || 0}
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(Math.max(0, page - 1))}
                  disabled={page === 0}
                  className="p-2 rounded-lg border hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="w-5 h-5" />
                </button>
                <span className="text-sm text-gray-600">
                  Seite {page + 1} von {totalPages}
                </span>
                <button
                  onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                  disabled={page >= totalPages - 1}
                  className="p-2 rounded-lg border hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronRight className="w-5 h-5" />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
