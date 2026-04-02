import { Suspense } from 'react'
import { SystemHealth, ImprovementTrends, ActiveExecutions } from '@/components/dashboard'
import { Skeleton } from '@/components/ui/skeleton'

export default function DashboardPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-gray-500 mt-1">Self-evolving agent system overview</p>
      </div>

      {/* System Health - top section */}
      <Suspense fallback={<Skeleton className="h-40" />}>
        <SystemHealth />
      </Suspense>

      {/* Two-column layout for trends and executions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Improvement Trends - 2/3 width */}
        <div className="lg:col-span-2">
          <Suspense fallback={<Skeleton className="h-[400px]" />}>
            <ImprovementTrends />
          </Suspense>
        </div>

        {/* Active Executions - 1/3 width */}
        <div>
          <Suspense fallback={<Skeleton className="h-[400px]" />}>
            <ActiveExecutions />
          </Suspense>
        </div>
      </div>
    </div>
  )
}
