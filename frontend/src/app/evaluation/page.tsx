import { Suspense } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  ColdResetPanel,
  WarmSnapshotPanel,
  BenchmarkRunner,
  RunResultsList,
} from '@/components/evaluation'

export const metadata = {
  title: 'Evaluation · Lumari',
  description: 'Run benchmarks, manage cold/warm resets, and view evaluation results.',
}

export default function EvaluationPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Evaluation</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Manage evaluation runs: reset the system state, configure and start
          benchmark suites with ablation modes, and review Pass@1 results.
        </p>
      </div>

      <Tabs defaultValue="reset" className="w-full">
        <TabsList>
          <TabsTrigger value="reset">Reset &amp; Snapshots</TabsTrigger>
          <TabsTrigger value="benchmark">Run Benchmark</TabsTrigger>
          <TabsTrigger value="results">Results</TabsTrigger>
        </TabsList>

        <TabsContent value="reset" className="mt-4 space-y-4">
          <Suspense fallback={null}>
            <ColdResetPanel />
          </Suspense>
          <Suspense fallback={null}>
            <WarmSnapshotPanel />
          </Suspense>
        </TabsContent>

        <TabsContent value="benchmark" className="mt-4">
          <Suspense fallback={null}>
            <BenchmarkRunner />
          </Suspense>
        </TabsContent>

        <TabsContent value="results" className="mt-4">
          <Suspense fallback={null}>
            <RunResultsList />
          </Suspense>
        </TabsContent>
      </Tabs>
    </div>
  )
}
