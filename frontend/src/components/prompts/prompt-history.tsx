'use client'

import { useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { PromptDiff } from './prompt-diff'
import { fetchPromptVersions } from '@/lib/api'
import type { Prompt } from '@/types'

interface PromptHistoryProps {
  promptId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface VersionMetrics {
  version: number
  successRate: number
  avgLatency: number
  executions: number
}

export function PromptHistory({ promptId, open, onOpenChange }: PromptHistoryProps) {
  const [versions, setVersions] = useState<Prompt[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedVersions, setSelectedVersions] = useState<[number, number]>([0, 1])

  useEffect(() => {
    if (!open) return

    async function load() {
      setLoading(true)
      try {
        const data = await fetchPromptVersions(promptId)
        setVersions(data)
        if (data.length >= 2) {
          setSelectedVersions([0, 1])
        }
      } catch (error) {
        console.error('Failed to fetch versions:', error)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [promptId, open])

  // Mock performance metrics (in production, would come from telemetry)
  const getMetrics = (version: Prompt, idx: number): VersionMetrics => ({
    version: idx + 1,
    successRate: 75 + Math.random() * 20,
    avgLatency: 100 + Math.random() * 200,
    executions: Math.floor(10 + Math.random() * 100),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Prompt Version History</DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="space-y-4">
            <Skeleton className="h-20" />
            <Skeleton className="h-40" />
          </div>
        ) : versions.length === 0 ? (
          <p className="text-gray-500">No version history available</p>
        ) : (
          <div className="space-y-6">
            {/* Version selector */}
            <div className="flex items-center gap-4">
              <div>
                <label className="text-sm text-gray-500">Compare:</label>
                <select
                  value={selectedVersions[0]}
                  onChange={(e) => setSelectedVersions([Number(e.target.value), selectedVersions[1]])}
                  className="ml-2 px-2 py-1 border rounded text-sm"
                >
                  {versions.map((_, i) => (
                    <option key={i} value={i}>v{i + 1}</option>
                  ))}
                </select>
              </div>
              <span className="text-gray-400">-&gt;</span>
              <div>
                <select
                  value={selectedVersions[1]}
                  onChange={(e) => setSelectedVersions([selectedVersions[0], Number(e.target.value)])}
                  className="px-2 py-1 border rounded text-sm"
                >
                  {versions.map((_, i) => (
                    <option key={i} value={i}>v{i + 1}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Performance metrics for each version */}
            <div className="grid grid-cols-2 gap-4">
              {[selectedVersions[0], selectedVersions[1]].map((vIdx) => {
                const metrics = getMetrics(versions[vIdx], vIdx)
                return (
                  <div key={vIdx} className="p-3 bg-gray-50 rounded-lg">
                    <h4 className="font-medium text-sm mb-2">v{metrics.version} Performance</h4>
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <span className="text-gray-500">Success</span>
                        <p className="font-semibold">{metrics.successRate.toFixed(1)}%</p>
                      </div>
                      <div>
                        <span className="text-gray-500">Latency</span>
                        <p className="font-semibold">{Math.round(metrics.avgLatency)}ms</p>
                      </div>
                      <div>
                        <span className="text-gray-500">Executions</span>
                        <p className="font-semibold">{metrics.executions}</p>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Diff view */}
            {versions[selectedVersions[0]] && versions[selectedVersions[1]] && (
              <div className="border rounded-lg p-4">
                <h4 className="font-medium text-sm mb-3">Changes</h4>
                <PromptDiff
                  oldContent={versions[selectedVersions[0]].content}
                  newContent={versions[selectedVersions[1]].content}
                  oldVersion={selectedVersions[0] + 1}
                  newVersion={selectedVersions[1] + 1}
                />
              </div>
            )}

            {/* Version timeline */}
            <div>
              <h4 className="font-medium text-sm mb-3">All Versions</h4>
              <div className="space-y-2">
                {versions.map((version, i) => (
                  <div
                    key={version.id}
                    className={`flex items-center justify-between p-2 rounded cursor-pointer transition-colors ${
                      selectedVersions.includes(i)
                        ? 'bg-indigo-50 border border-indigo-200'
                        : 'hover:bg-gray-50'
                    }`}
                    onClick={() => {
                      if (!selectedVersions.includes(i)) {
                        setSelectedVersions([selectedVersions[1], i])
                      }
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">v{i + 1}</span>
                      {i === versions.length - 1 && (
                        <span className="text-xs px-1.5 py-0.5 bg-green-100 text-green-700 rounded">
                          Latest
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-400">
                      {new Date(version.created_at).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
