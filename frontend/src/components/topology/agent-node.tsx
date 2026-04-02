'use client'

import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'

export type AgentStatus = 'idle' | 'running' | 'complete' | 'error'

export interface AgentNodeData extends Record<string, unknown> {
  name: string
  capabilities: string[]
  isActive: boolean
  status?: AgentStatus
  onClick?: () => void
}

export type AgentNodeType = Node<AgentNodeData>

function AgentNodeComponent({ data, selected }: NodeProps<AgentNodeType>) {
  const { name, capabilities, isActive, status = 'idle', onClick } = data as AgentNodeData

  const statusStyles = {
    idle: 'bg-white border-gray-200',
    running: 'bg-blue-50 border-blue-400 shadow-lg shadow-blue-200 animate-pulse',
    complete: 'bg-green-50 border-green-400',
    error: 'bg-red-50 border-red-400',
  }

  const statusIcons = {
    idle: null,
    running: <span className="w-2 h-2 rounded-full bg-blue-500 animate-ping" />,
    complete: <span className="text-green-600 font-bold">&#10003;</span>,
    error: <span className="text-red-600 font-bold">&#10005;</span>,
  }

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div
        onClick={onClick}
        className={`
          px-4 py-3 rounded-lg border-2 cursor-pointer transition-all
          ${statusStyles[status]}
          ${selected ? 'ring-2 ring-indigo-500 ring-offset-2' : ''}
          ${isActive ? '' : 'opacity-50'}
          hover:shadow-md
        `}
        style={{ width: 180, minWidth: 180 }}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium text-sm truncate">{name}</span>
          {statusIcons[status]}
        </div>

        {capabilities.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {capabilities.slice(0, 3).map((cap) => (
              <span
                key={cap}
                className="text-xs px-1.5 py-0.5 bg-gray-100 rounded text-gray-600"
              >
                {cap}
              </span>
            ))}
            {capabilities.length > 3 && (
              <span className="text-xs text-gray-400">+{capabilities.length - 3}</span>
            )}
          </div>
        )}

        {!isActive && (
          <div className="mt-1 text-xs text-gray-400">Inactive</div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </>
  )
}

export const AgentNode = memo(AgentNodeComponent)
