'use client'

import { useEffect, useState, useMemo } from 'react'
import { PromptCard } from './prompt-card'
import { PromptHistory } from './prompt-history'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchPrompts } from '@/lib/api'
import type { Prompt } from '@/types'

export function PromptList() {
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [historyPromptId, setHistoryPromptId] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchPrompts()
        setPrompts(data)
      } catch (error) {
        console.error('Failed to fetch prompts:', error)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const filteredPrompts = useMemo(() => {
    if (search === '') return prompts
    return prompts.filter(
      (p) =>
        p.name.toLowerCase().includes(search.toLowerCase()) ||
        p.content.toLowerCase().includes(search.toLowerCase())
    )
  }, [prompts, search])

  const stats = useMemo(() => {
    const active = prompts.filter((p) => p.is_active).length
    const withVersions = prompts.filter((p) => p.parent_id).length
    return { total: prompts.length, active, withVersions }
  }, [prompts])

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="flex items-center gap-4 text-sm text-gray-500">
        <span>{stats.total} total</span>
        <span className="text-green-600">{stats.active} active</span>
        <span className="text-indigo-600">{stats.withVersions} evolved</span>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search prompts..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
      />

      {/* Prompt Grid */}
      {filteredPrompts.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          {prompts.length === 0
            ? 'No prompts found'
            : 'No prompts match your search'}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredPrompts.map((prompt) => (
            <PromptCard
              key={prompt.id}
              prompt={prompt}
              onViewHistory={() => setHistoryPromptId(prompt.id)}
            />
          ))}
        </div>
      )}

      {/* History Dialog */}
      {historyPromptId && (
        <PromptHistory
          promptId={historyPromptId}
          open={Boolean(historyPromptId)}
          onOpenChange={(open) => !open && setHistoryPromptId(null)}
        />
      )}
    </div>
  )
}
