import { TopologyGraph } from '@/components/topology'

export default function TopologyPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Agent Topology</h1>
        <p className="text-gray-500 mt-1">Current agent connections and execution flow</p>
      </div>

      <TopologyGraph />
    </div>
  )
}
