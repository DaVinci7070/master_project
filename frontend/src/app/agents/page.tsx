import { AgentList } from '@/components/agents'

export default function AgentsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Agents</h1>
        <p className="text-gray-500 mt-1">All registered agents in the system</p>
      </div>

      <AgentList />
    </div>
  )
}
