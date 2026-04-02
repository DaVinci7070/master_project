'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { useTopologyUpdates } from '@/hooks'
import { AgentNode, type AgentNodeData, type AgentStatus } from './agent-node'
import { AgentPanel } from './agent-panel'
import type { Topology, AgentNode as AgentNodeType } from '@/types'
import { fetchTopology } from '@/lib/api'
import { Skeleton } from '@/components/ui/skeleton'

const nodeTypes = { agent: AgentNode }

interface TopologyGraphProps {
  executionId?: string
}

export function TopologyGraph({ executionId }: TopologyGraphProps) {
  const [topology, setTopology] = useState<Topology | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedAgent, setSelectedAgent] = useState<AgentNodeType | null>(null)
  const [agentStatuses, setAgentStatuses] = useState<Record<string, AgentStatus>>({})

  const { data: topologyEvent } = useTopologyUpdates()

  // Load initial topology
  useEffect(() => {
    async function load() {
      try {
        const data = await fetchTopology()
        setTopology(data)
      } catch (error) {
        console.error('Failed to load topology:', error)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  // Update topology from SSE
  useEffect(() => {
    if (topologyEvent?.topology) {
      setTopology(topologyEvent.topology)
    }
  }, [topologyEvent])

  // Calculate waves based on dependencies (topological sort)
  const calculateWaves = (agents: AgentNodeType[]): Map<string, number> => {
    const waveMap = new Map<string, number>()
    const agentMap = new Map(agents.map(a => [a.agent_id, a]))

    // Find agents with no dependencies - they're in wave 0
    const processed = new Set<string>()
    let currentWave = 0

    while (processed.size < agents.length) {
      const waveAgents: string[] = []

      for (const agent of agents) {
        if (processed.has(agent.agent_id)) continue

        // Check if all dependencies are processed
        const allDepsProcessed = agent.dependencies.every(
          dep => processed.has(dep) || !agentMap.has(dep)
        )

        if (allDepsProcessed) {
          waveAgents.push(agent.agent_id)
          waveMap.set(agent.agent_id, currentWave)
        }
      }

      // If no agents could be added, break (circular dependency)
      if (waveAgents.length === 0) {
        // Add remaining agents to current wave
        for (const agent of agents) {
          if (!processed.has(agent.agent_id)) {
            waveMap.set(agent.agent_id, currentWave)
            processed.add(agent.agent_id)
          }
        }
        break
      }

      waveAgents.forEach(id => processed.add(id))
      currentWave++
    }

    return waveMap
  }

  // Convert topology to React Flow nodes/edges with wave-based positioning
  const { layoutedNodes, layoutedEdges } = useMemo(() => {
    if (!topology) {
      return { layoutedNodes: [], layoutedEdges: [] }
    }

    // Calculate waves
    const waveMap = calculateWaves(topology.agents)

    // Group agents by wave
    const waveGroups = new Map<number, AgentNodeType[]>()
    for (const agent of topology.agents) {
      const wave = waveMap.get(agent.agent_id) ?? 0
      if (!waveGroups.has(wave)) {
        waveGroups.set(wave, [])
      }
      waveGroups.get(wave)!.push(agent)
    }

    // Layout constants - must match agent-node.tsx width (180px)
    const nodeWidth = 180
    const nodeHeight = 80
    const horizontalGap = 60  // Gap between nodes horizontally
    const verticalGap = 100   // Gap between waves vertically
    const startX = 20
    const startY = 20

    // Position nodes by wave
    const nodes: Node<AgentNodeData>[] = []
    const sortedWaves = Array.from(waveGroups.keys()).sort((a, b) => a - b)

    for (const wave of sortedWaves) {
      const waveAgents = waveGroups.get(wave)!
      const waveY = startY + wave * (nodeHeight + verticalGap)

      // Center the wave horizontally
      const totalWidth = waveAgents.length * nodeWidth + (waveAgents.length - 1) * horizontalGap
      const waveStartX = startX

      waveAgents.forEach((agent, index) => {
        nodes.push({
          id: agent.agent_id,
          type: 'agent',
          position: {
            x: waveStartX + index * (nodeWidth + horizontalGap),
            y: waveY,
          },
          data: {
            name: agent.name,
            capabilities: agent.capabilities,
            isActive: agent.is_active,
            status: agentStatuses[agent.agent_id] || 'idle',
            onClick: () => setSelectedAgent(agent),
          },
        })
      })
    }

    const edges: Edge[] = topology.agents.flatMap((agent) =>
      agent.dependencies.map((dep) => ({
        id: `${dep}-${agent.agent_id}`,
        source: dep,
        target: agent.agent_id,
        animated: agentStatuses[dep] === 'running',
        style: {
          stroke: agentStatuses[dep] === 'running' ? '#3b82f6' : '#94a3b8',
          strokeWidth: 2,
        },
      }))
    )

    return { layoutedNodes: nodes, layoutedEdges: edges }
  }, [topology, agentStatuses])

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutedEdges)

  // Update nodes when layout changes
  useEffect(() => {
    setNodes(layoutedNodes)
    setEdges(layoutedEdges)
  }, [layoutedNodes, layoutedEdges, setNodes, setEdges])

  if (loading) {
    return <Skeleton className="w-full h-[600px]" />
  }

  if (!topology) {
    return (
      <div className="flex items-center justify-center h-[600px] text-gray-500">
        Failed to load topology
      </div>
    )
  }

  return (
    <div className="flex h-[600px] border rounded-lg overflow-hidden">
      <div className="flex-1">
        <ReactFlow
          key={topology?.topology_id || 'loading'}
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2, minZoom: 0.5, maxZoom: 1.5 }}
          nodesDraggable={true}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
          maxZoom={2}
        >
          <Background />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={(node) => {
              const status = (node.data as AgentNodeData).status
              if (status === 'running') return '#3b82f6'
              if (status === 'complete') return '#22c55e'
              if (status === 'error') return '#ef4444'
              return '#94a3b8'
            }}
          />
        </ReactFlow>
      </div>

      {/* Side panel per CONTEXT - slides out when agent clicked */}
      {selectedAgent && (
        <AgentPanel
          agent={selectedAgent}
          onClose={() => setSelectedAgent(null)}
        />
      )}
    </div>
  )
}
