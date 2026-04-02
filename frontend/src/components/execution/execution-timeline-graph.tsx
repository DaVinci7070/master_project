'use client'

import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { CheckCircle, Circle, Loader2, XCircle, Clock } from 'lucide-react'

export type AgentStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface TimelineAgent {
  id: string
  name: string
  wave: number
  status: AgentStatus
  startedAt?: string
  completedAt?: string
  durationMs?: number
}

interface ExecutionTimelineGraphProps {
  agents: TimelineAgent[]
  currentAgentId?: string
  className?: string
}

function AgentNode({
  agent,
  isActive,
  isLast,
}: {
  agent: TimelineAgent
  isActive: boolean
  isLast: boolean
}) {
  const statusColors = {
    pending: 'bg-gray-200 border-gray-300 text-gray-500',
    running: 'bg-blue-100 border-blue-400 text-blue-700 animate-pulse',
    completed: 'bg-green-100 border-green-400 text-green-700',
    failed: 'bg-red-100 border-red-400 text-red-700',
  }

  const StatusIcon = {
    pending: Circle,
    running: Loader2,
    completed: CheckCircle,
    failed: XCircle,
  }[agent.status]

  return (
    <div className="flex items-center">
      {/* Agent card */}
      <div
        className={cn(
          'relative flex flex-col items-center p-3 rounded-lg border-2 min-w-[120px] transition-all duration-300',
          statusColors[agent.status],
          isActive && 'ring-4 ring-blue-400 ring-opacity-50 scale-105 shadow-lg'
        )}
      >
        {/* Wave badge */}
        <div className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-gray-700 text-white text-xs flex items-center justify-center font-bold">
          {agent.wave}
        </div>

        {/* Status icon */}
        <StatusIcon
          className={cn(
            'w-8 h-8 mb-2',
            agent.status === 'running' && 'animate-spin'
          )}
        />

        {/* Agent name */}
        <span className="text-sm font-medium text-center whitespace-nowrap overflow-hidden text-ellipsis max-w-[100px]">
          {agent.name.replace('_agent', '').replace(/_/g, ' ')}
        </span>

        {/* Duration */}
        {agent.durationMs !== undefined && agent.status === 'completed' && (
          <span className="text-xs mt-1 opacity-75">
            {(agent.durationMs / 1000).toFixed(1)}s
          </span>
        )}

        {/* Running indicator */}
        {agent.status === 'running' && (
          <div className="absolute -bottom-1 left-1/2 -translate-x-1/2">
            <div className="flex gap-1">
              <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          </div>
        )}
      </div>

      {/* Connector line */}
      {!isLast && (
        <div className="flex items-center mx-2">
          <div
            className={cn(
              'h-1 w-8 rounded transition-colors duration-300',
              agent.status === 'completed' ? 'bg-green-400' :
              agent.status === 'running' ? 'bg-blue-400' :
              'bg-gray-300'
            )}
          />
          <div
            className={cn(
              'w-0 h-0 border-t-[6px] border-t-transparent border-b-[6px] border-b-transparent border-l-[8px] transition-colors duration-300',
              agent.status === 'completed' ? 'border-l-green-400' :
              agent.status === 'running' ? 'border-l-blue-400' :
              'border-l-gray-300'
            )}
          />
        </div>
      )}
    </div>
  )
}

export function ExecutionTimelineGraph({
  agents,
  currentAgentId,
  className,
}: ExecutionTimelineGraphProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const activeAgentRef = useRef<HTMLDivElement>(null)
  const [showLeftFade, setShowLeftFade] = useState(false)
  const [showRightFade, setShowRightFade] = useState(false)

  // Auto-scroll to active agent
  useEffect(() => {
    if (currentAgentId && scrollContainerRef.current) {
      const activeElement = scrollContainerRef.current.querySelector(
        `[data-agent-id="${currentAgentId}"]`
      )
      if (activeElement) {
        activeElement.scrollIntoView({
          behavior: 'smooth',
          block: 'nearest',
          inline: 'center',
        })
      }
    }
  }, [currentAgentId])

  // Check scroll position for fade indicators
  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return

    const handleScroll = () => {
      setShowLeftFade(container.scrollLeft > 20)
      setShowRightFade(
        container.scrollLeft < container.scrollWidth - container.clientWidth - 20
      )
    }

    handleScroll()
    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [agents])

  // Group agents by wave
  const waves = agents.reduce((acc, agent) => {
    if (!acc[agent.wave]) acc[agent.wave] = []
    acc[agent.wave].push(agent)
    return acc
  }, {} as Record<number, TimelineAgent[]>)

  const waveNumbers = Object.keys(waves).map(Number).sort((a, b) => a - b)

  // Calculate progress
  const completedCount = agents.filter(a => a.status === 'completed').length
  const runningCount = agents.filter(a => a.status === 'running').length
  const progress = agents.length > 0 ? (completedCount / agents.length) * 100 : 0

  if (agents.length === 0) {
    return (
      <div className={cn('bg-white rounded-lg border p-4', className)}>
        <div className="flex items-center justify-center h-24 text-gray-400">
          <Clock className="w-5 h-5 mr-2" />
          <span>Warten auf Agent-Aktivität...</span>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('bg-white rounded-lg border overflow-hidden', className)}>
      {/* Header with progress */}
      <div className="px-4 py-3 border-b bg-gray-50">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-sm">Agent-Timeline</h3>
          <div className="flex items-center gap-4 text-xs">
            <span className="text-gray-500">
              {completedCount}/{agents.length} abgeschlossen
            </span>
            {runningCount > 0 && (
              <span className="text-blue-600 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                {runningCount} aktiv
              </span>
            )}
          </div>
        </div>
        {/* Progress bar */}
        <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-blue-500 to-green-500 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Scrollable timeline */}
      <div className="relative">
        {/* Left fade */}
        {showLeftFade && (
          <div className="absolute left-0 top-0 bottom-0 w-12 bg-gradient-to-r from-white to-transparent z-10 pointer-events-none" />
        )}

        {/* Right fade */}
        {showRightFade && (
          <div className="absolute right-0 top-0 bottom-0 w-12 bg-gradient-to-l from-white to-transparent z-10 pointer-events-none" />
        )}

        <div
          ref={scrollContainerRef}
          className="overflow-x-auto scrollbar-thin scrollbar-thumb-gray-300 scrollbar-track-gray-100"
        >
          <div className="flex items-center gap-6 p-4 min-w-max">
            {waveNumbers.map((waveNum, waveIdx) => (
              <div key={waveNum} className="flex items-center">
                {/* Wave separator */}
                {waveIdx > 0 && (
                  <div className="flex flex-col items-center mx-4">
                    <div className="w-px h-8 bg-gray-300" />
                    <span className="text-xs text-gray-400 my-1">Wave {waveNum}</span>
                    <div className="w-px h-8 bg-gray-300" />
                  </div>
                )}

                {/* Agents in this wave (can run in parallel) */}
                <div className="flex flex-col gap-3">
                  {waves[waveNum].map((agent, idx) => (
                    <div
                      key={agent.id}
                      data-agent-id={agent.id}
                      ref={agent.id === currentAgentId ? activeAgentRef : undefined}
                    >
                      <AgentNode
                        agent={agent}
                        isActive={agent.id === currentAgentId || agent.status === 'running'}
                        isLast={waveIdx === waveNumbers.length - 1 && idx === waves[waveNum].length - 1}
                      />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="px-4 py-2 border-t bg-gray-50 flex items-center gap-4 text-xs">
        <div className="flex items-center gap-1">
          <Circle className="w-3 h-3 text-gray-400" />
          <span className="text-gray-500">Ausstehend</span>
        </div>
        <div className="flex items-center gap-1">
          <Loader2 className="w-3 h-3 text-blue-500" />
          <span className="text-gray-500">Aktiv</span>
        </div>
        <div className="flex items-center gap-1">
          <CheckCircle className="w-3 h-3 text-green-500" />
          <span className="text-gray-500">Fertig</span>
        </div>
        <div className="flex items-center gap-1">
          <XCircle className="w-3 h-3 text-red-500" />
          <span className="text-gray-500">Fehler</span>
        </div>
      </div>
    </div>
  )
}
