'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import type { AgentNode as AgentNodeType } from '@/types'

interface AgentPanelProps {
  agent: AgentNodeType | null
  onClose: () => void
}

export function AgentPanel({ agent, onClose }: AgentPanelProps) {
  if (!agent) return null

  return (
    <div className="w-80 border-l bg-white p-4 overflow-y-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-lg">Agent Details</h2>
        <Button variant="ghost" size="sm" onClick={onClose}>
          ✕
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{agent.name}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-sm text-gray-500 mb-1">Status</p>
            <span className={`text-sm font-medium ${agent.is_active ? 'text-green-600' : 'text-gray-400'}`}>
              {agent.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>

          <div>
            <p className="text-sm text-gray-500 mb-1">Agent ID</p>
            <p className="font-mono text-xs">{agent.agent_id}</p>
          </div>

          {agent.capabilities.length > 0 && (
            <div>
              <p className="text-sm text-gray-500 mb-1">Capabilities</p>
              <div className="flex flex-wrap gap-1">
                {agent.capabilities.map((cap) => (
                  <span
                    key={cap}
                    className="text-xs px-2 py-1 bg-indigo-100 text-indigo-700 rounded"
                  >
                    {cap}
                  </span>
                ))}
              </div>
            </div>
          )}

          {agent.dependencies.length > 0 && (
            <div>
              <p className="text-sm text-gray-500 mb-1">Dependencies</p>
              <div className="space-y-1">
                {agent.dependencies.map((dep) => (
                  <p key={dep} className="text-sm font-mono">{dep}</p>
                ))}
              </div>
            </div>
          )}

          {agent.skill_ids.length > 0 && (
            <div>
              <p className="text-sm text-gray-500 mb-1">Skills ({agent.skill_ids.length})</p>
              <div className="space-y-1">
                {agent.skill_ids.slice(0, 5).map((id) => (
                  <p key={id} className="text-xs font-mono text-gray-600">{id.slice(0, 8)}</p>
                ))}
                {agent.skill_ids.length > 5 && (
                  <p className="text-xs text-gray-400">+{agent.skill_ids.length - 5} more</p>
                )}
              </div>
            </div>
          )}

          {agent.prompt_id && (
            <div>
              <p className="text-sm text-gray-500 mb-1">Prompt ID</p>
              <p className="font-mono text-xs">{agent.prompt_id}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
