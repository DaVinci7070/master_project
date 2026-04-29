import { Suspense } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  MetricCorrelationChart,
  PromptEvolutionTimeline,
  SkillEvolutionView,
  TopologyChangeHistory,
} from '@/components/evolution'

export const metadata = {
  title: 'Evolution · Lumari',
  description: 'Longitudinal view of prompt, skill and topology evolution.',
}

export default function EvolutionPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Evolution</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Longitudinal view of how prompts, skills and topology change across
          executions. The evolution loop writes new versions after each run — this
          page is where you watch it happen.
        </p>
      </div>

      <Tabs defaultValue="prompts" className="w-full">
        <TabsList>
          <TabsTrigger value="prompts">Prompts</TabsTrigger>
          <TabsTrigger value="skills">Skills</TabsTrigger>
          <TabsTrigger value="topology">Topology</TabsTrigger>
          <TabsTrigger value="correlations">Correlations</TabsTrigger>
        </TabsList>

        <TabsContent value="prompts" className="mt-4">
          <Suspense fallback={null}>
            <PromptEvolutionTimeline />
          </Suspense>
        </TabsContent>

        <TabsContent value="skills" className="mt-4">
          <Suspense fallback={null}>
            <SkillEvolutionView />
          </Suspense>
        </TabsContent>

        <TabsContent value="topology" className="mt-4">
          <Suspense fallback={null}>
            <TopologyChangeHistory />
          </Suspense>
        </TabsContent>

        <TabsContent value="correlations" className="mt-4">
          <Suspense fallback={null}>
            <MetricCorrelationChart />
          </Suspense>
        </TabsContent>
      </Tabs>
    </div>
  )
}