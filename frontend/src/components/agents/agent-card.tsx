'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { Agent } from '@/types'

interface AgentCardProps {
  agent: Agent
  onClick?: () => void
}

export function AgentCard({ agent, onClick }: AgentCardProps) {
  const sourceColors = {
    initial: 'bg-gray-100 text-gray-600',
    system_generated: 'bg-purple-100 text-purple-700',
    manual: 'bg-blue-100 text-blue-700',
  }

  const sourceLabels = {
    initial: 'Original',
    system_generated: 'System-Generated',
    manual: 'Manual',
  }

  const source = agent.source || 'initial'

  return (
    <Card
      className={`cursor-pointer transition-all hover:shadow-md ${
        agent.is_active ? '' : 'opacity-60'
      }`}
      onClick={onClick}
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">{agent.name}</CardTitle>
          <div className="flex items-center gap-2">
            {source === 'system_generated' && (
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${sourceColors[source]}`}>
                {sourceLabels[source]}
              </span>
            )}
            <span
              className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                agent.is_active
                  ? 'bg-green-100 text-green-700'
                  : 'bg-gray-100 text-gray-500'
              }`}
            >
              {agent.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {/* Capabilities */}
          {agent.capabilities.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-1">Capabilities</p>
              <div className="flex flex-wrap gap-1">
                {agent.capabilities.slice(0, 4).map((cap) => (
                  <span
                    key={cap}
                    className="text-xs px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded"
                  >
                    {cap}
                  </span>
                ))}
                {agent.capabilities.length > 4 && (
                  <span className="text-xs text-gray-400">
                    +{agent.capabilities.length - 4}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Dependencies */}
          {agent.dependencies.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-1">Dependencies</p>
              <p className="text-sm text-gray-600">
                {agent.dependencies.join(', ')}
              </p>
            </div>
          )}

          {/* Metadata */}
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>ID: {agent.id.slice(0, 8)}</span>
            <span>{new Date(agent.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
