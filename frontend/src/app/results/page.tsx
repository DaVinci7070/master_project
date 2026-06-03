import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Rq1Evolution, Rq2BlueprintReuse, Rq3Gatekeeper } from '@/components/results'
import { THESIS_META } from '@/data/thesis-results'

export const metadata = {
  title: 'Ergebnisse · Lumari',
  description: 'Benchmark-Ergebnisse der Masterarbeit zu den Forschungsfragen RQ1–RQ3.',
}

export default function ResultsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Ergebnisse</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Zentrale Benchmark-Ergebnisse der Masterarbeit zu den drei Forschungsfragen. Die Zahlen sind
          fest hinterlegt (Stand {THESIS_META.generatedAt}, Suite{' '}
          <span className="font-mono">{THESIS_META.suite}</span>) und werden ohne laufende Benchmarks
          angezeigt.
        </p>
        <p className="mt-2 text-xs text-muted-foreground">{THESIS_META.note}</p>
      </div>

      <Tabs defaultValue="rq1" className="w-full">
        <TabsList>
          <TabsTrigger value="rq1">RQ1 · Selbst-Evolution</TabsTrigger>
          <TabsTrigger value="rq2">RQ2 · Blueprint-Reuse</TabsTrigger>
          <TabsTrigger value="rq3">RQ3 · Gatekeeper</TabsTrigger>
        </TabsList>

        <TabsContent value="rq1" className="mt-6">
          <Rq1Evolution />
        </TabsContent>
        <TabsContent value="rq2" className="mt-6">
          <Rq2BlueprintReuse />
        </TabsContent>
        <TabsContent value="rq3" className="mt-6">
          <Rq3Gatekeeper />
        </TabsContent>
      </Tabs>
    </div>
  )
}
