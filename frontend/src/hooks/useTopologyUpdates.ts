'use client'

import { useSSE } from './useSSE'
import type { Topology } from '@/types'

export interface TopologyEvent {
  type: 'agent_added' | 'agent_removed' | 'topology_updated'
  topology?: Topology
  agent_id?: string
  timestamp: string
}

export function useTopologyUpdates() {
  return useSSE<TopologyEvent>('/api/backend/events/topology')
}
