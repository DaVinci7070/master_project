'use client'

import { useEffect, useState, useMemo } from 'react'
import { AgentCard } from './agent-card'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchAgents } from '@/lib/api'
import type { Agent } from '@/types'

type StatusFilter = 'all' | 'active' | 'inactive'
type SourceFilter = 'all' | 'initial' | 'system_generated' | 'manual'

export function AgentList() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchAgents()
        setAgents(data)
      } catch (error) {
        console.error('Failed to fetch agents:', error)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const filteredAgents = useMemo(() => {
    return agents.filter((agent) => {
      // Search filter
      const searchMatch =
        search === '' ||
        agent.name.toLowerCase().includes(search.toLowerCase()) ||
        agent.capabilities.some((cap) =>
          cap.toLowerCase().includes(search.toLowerCase())
        )

      // Status filter
      const statusMatch =
        statusFilter === 'all' ||
        (statusFilter === 'active' && agent.is_active) ||
        (statusFilter === 'inactive' && !agent.is_active)

      // Source filter
      const agentSource = agent.source || 'initial'
      const sourceMatch =
        sourceFilter === 'all' || agentSource === sourceFilter

      return searchMatch && statusMatch && sourceMatch
    })
  }, [agents, search, statusFilter, sourceFilter])

  const stats = useMemo(() => {
    const active = agents.filter((a) => a.is_active).length
    const systemGenerated = agents.filter((a) => a.source === 'system_generated').length
    return {
      total: agents.length,
      active,
      inactive: agents.length - active,
      systemGenerated,
    }
  }, [agents])

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex gap-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-10 w-32" />
        </div>
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
        <span className="text-gray-400">{stats.inactive} inactive</span>
        {stats.systemGenerated > 0 && (
          <span className="text-purple-600">{stats.systemGenerated} system-generated</span>
        )}
      </div>

      {/* Search and Filter */}
      <div className="flex flex-col sm:flex-row gap-4">
        <input
          type="text"
          placeholder="Search agents or capabilities..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        >
          <option value="all">All Status</option>
          <option value="active">Active Only</option>
          <option value="inactive">Inactive Only</option>
        </select>
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        >
          <option value="all">All Sources</option>
          <option value="initial">Original</option>
          <option value="system_generated">System-Generated</option>
          <option value="manual">Manual</option>
        </select>
      </div>

      {/* Agent Grid */}
      {filteredAgents.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          {agents.length === 0
            ? 'No agents found'
            : 'No agents match your search'}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredAgents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  )
}
