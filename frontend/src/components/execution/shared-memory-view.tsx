'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Database, Lightbulb, AlertCircle } from 'lucide-react'

interface Fact {
  id: string
  text: string
  confidence: number
  source_agent_id: string
  tags: string[]
  created_at: string
}

interface Hypothesis {
  id: string
  text: string
  confidence: number
  status: string
  source_agent_id: string
  supporting_fact_ids: string[]
  contradicting_fact_ids: string[]
  created_at: string
}

interface SharedMemoryData {
  execution_id: string
  facts: {
    total: number
    by_agent: Record<string, Fact[]>
    items: Fact[]
  }
  hypotheses: {
    total: number
    by_agent: Record<string, Hypothesis[]>
    items: Hypothesis[]
  }
}

interface SharedMemoryViewProps {
  executionId: string
}

export function SharedMemoryView({ executionId }: SharedMemoryViewProps) {
  const [data, setData] = useState<SharedMemoryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    async function fetchSharedMemory() {
      try {
        setLoading(true)
        const response = await fetch(`/api/backend/shared-memory/execution/${executionId}`)
        if (!response.ok) {
          throw new Error('Failed to fetch shared memory')
        }
        const result = await response.json()
        setData(result)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      } finally {
        setLoading(false)
      }
    }

    fetchSharedMemory()
  }, [executionId])

  if (loading) {
    return (
      <div className="bg-white rounded-lg border p-6">
        <div className="animate-pulse flex items-center gap-3">
          <div className="w-6 h-6 bg-gray-200 rounded"></div>
          <div className="h-6 bg-gray-200 rounded w-48"></div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 rounded-lg border border-red-200 p-6">
        <div className="flex items-center gap-3 text-red-700">
          <AlertCircle className="w-5 h-5" />
          <span>Shared Memory konnte nicht geladen werden: {error}</span>
        </div>
      </div>
    )
  }

  if (!data || (data.facts.total === 0 && data.hypotheses.total === 0)) {
    return (
      <div className="bg-gray-50 rounded-lg border p-6">
        <div className="flex items-center gap-3 text-gray-500">
          <Database className="w-5 h-5" />
          <span>Keine Shared Memory Einträge für diese Execution</span>
        </div>
      </div>
    )
  }

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      active: 'bg-blue-100 text-blue-700',
      confirmed: 'bg-green-100 text-green-700',
      contradicted: 'bg-red-100 text-red-700',
    }
    return styles[status] || 'bg-gray-100 text-gray-700'
  }

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return 'text-green-600'
    if (confidence >= 0.5) return 'text-yellow-600'
    return 'text-red-600'
  }

  return (
    <div className="bg-white rounded-lg border overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full p-6 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <Database className="w-6 h-6 text-purple-600" />
          <div className="text-left">
            <h2 className="text-lg font-semibold">Shared Memory</h2>
            <p className="text-sm text-gray-500">
              {data.facts.total} Fakten, {data.hypotheses.total} Hypothesen
            </p>
          </div>
        </div>
        {isOpen ? (
          <ChevronUp className="w-5 h-5 text-gray-400" />
        ) : (
          <ChevronDown className="w-5 h-5 text-gray-400" />
        )}
      </button>

      {isOpen && (
        <div className="border-t p-6 space-y-6">
          {/* Facts Section */}
          {data.facts.total > 0 && (
            <div>
              <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <span className="w-3 h-3 bg-blue-500 rounded-full"></span>
                Fakten ({data.facts.total})
              </h3>
              <div className="space-y-4">
                {Object.entries(data.facts.by_agent).map(([agentId, facts]) => (
                  <div key={agentId} className="bg-gray-50 rounded-lg p-4">
                    <h4 className="text-sm font-medium text-gray-500 mb-3">
                      Agent: {agentId.slice(0, 8)}...
                    </h4>
                    <div className="space-y-3">
                      {facts.map((fact) => (
                        <div
                          key={fact.id}
                          className="bg-white rounded border p-3"
                        >
                          <p className="text-gray-800">{fact.text}</p>
                          <div className="flex items-center gap-4 mt-2 text-sm">
                            <span className={getConfidenceColor(fact.confidence)}>
                              Konfidenz: {(fact.confidence * 100).toFixed(0)}%
                            </span>
                            {fact.tags && fact.tags.length > 0 && (
                              <div className="flex gap-1">
                                {fact.tags.map((tag) => (
                                  <span
                                    key={tag}
                                    className="px-2 py-0.5 bg-gray-100 rounded text-xs text-gray-600"
                                  >
                                    {tag}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Hypotheses Section */}
          {data.hypotheses.total > 0 && (
            <div>
              <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Lightbulb className="w-4 h-4 text-yellow-500" />
                Hypothesen ({data.hypotheses.total})
              </h3>
              <div className="space-y-4">
                {Object.entries(data.hypotheses.by_agent).map(([agentId, hypotheses]) => (
                  <div key={agentId} className="bg-gray-50 rounded-lg p-4">
                    <h4 className="text-sm font-medium text-gray-500 mb-3">
                      Agent: {agentId.slice(0, 8)}...
                    </h4>
                    <div className="space-y-3">
                      {hypotheses.map((hyp) => (
                        <div
                          key={hyp.id}
                          className={`bg-white rounded border p-3 ${
                            hyp.contradicting_fact_ids?.length > 0
                              ? 'border-red-200 bg-red-50'
                              : ''
                          }`}
                        >
                          <div className="flex items-start justify-between gap-4">
                            <p className="text-gray-800">{hyp.text}</p>
                            <span
                              className={`px-2 py-1 rounded text-xs font-medium whitespace-nowrap ${getStatusBadge(
                                hyp.status
                              )}`}
                            >
                              {hyp.status}
                            </span>
                          </div>
                          <div className="flex items-center gap-4 mt-2 text-sm">
                            <span className={getConfidenceColor(hyp.confidence)}>
                              Konfidenz: {(hyp.confidence * 100).toFixed(0)}%
                            </span>
                            {hyp.supporting_fact_ids?.length > 0 && (
                              <span className="text-green-600">
                                {hyp.supporting_fact_ids.length} unterstützende Fakten
                              </span>
                            )}
                            {hyp.contradicting_fact_ids?.length > 0 && (
                              <span className="text-red-600">
                                {hyp.contradicting_fact_ids.length} widersprechende Fakten
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
