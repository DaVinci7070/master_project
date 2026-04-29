'use client'

import { useState } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { triggerColdReset } from '@/lib/api'
import type { ColdResetResponse } from '@/types'

export function ColdResetPanel() {
  const [skipSeed, setSkipSeed] = useState(false)
  const [skipQdrant, setSkipQdrant] = useState(false)
  const [dryRun, setDryRun] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ColdResetResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleReset() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const response = await triggerColdReset({
        skip_seed: skipSeed,
        skip_qdrant: skipQdrant,
        dry_run: dryRun,
      })
      setResult(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cold reset failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cold Reset</CardTitle>
        <CardDescription>
          Truncate all tables, clear Qdrant vectors, and re-seed default agents.
          Use this before each evaluation run for a clean baseline.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <Label htmlFor="dry-run">Dry Run (preview only)</Label>
            <Switch id="dry-run" checked={dryRun} onCheckedChange={setDryRun} />
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="skip-seed">Skip agent re-seeding</Label>
            <Switch id="skip-seed" checked={skipSeed} onCheckedChange={setSkipSeed} />
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="skip-qdrant">Skip Qdrant cleanup</Label>
            <Switch id="skip-qdrant" checked={skipQdrant} onCheckedChange={setSkipQdrant} />
          </div>
        </div>

        {dryRun ? (
          <Button onClick={handleReset} disabled={loading} className="w-full">
            {loading ? 'Running dry run...' : 'Preview Cold Reset (Dry Run)'}
          </Button>
        ) : (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" className="w-full" disabled={loading}>
                {loading ? 'Resetting...' : 'Execute Cold Reset'}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle className="text-destructive">
                  Confirm Cold Reset
                </AlertDialogTitle>
                <AlertDialogDescription asChild>
                  <div className="space-y-2">
                    <p>This will permanently delete all data:</p>
                    <ul className="list-disc list-inside text-sm space-y-1">
                      <li>All execution results and telemetry</li>
                      <li>All skills, prompts, and agents (except re-seeded defaults)</li>
                      <li>All evolution history and improvement attempts</li>
                      {!skipQdrant && <li>All Qdrant vector collections</li>}
                    </ul>
                  </div>
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={(e) => {
                    e.preventDefault()
                    handleReset()
                  }}
                  className="bg-destructive hover:bg-destructive/90"
                >
                  Yes, Reset Everything
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}

        {result && (
          <div className={`p-3 rounded-lg text-sm space-y-1 ${
            result.dry_run ? 'bg-blue-50 text-blue-700' : 'bg-green-50 text-green-700'
          }`}>
            <p className="font-medium">
              {result.dry_run ? 'Dry run complete (no changes made)' : 'Cold reset complete'}
            </p>
            <ul className="text-xs space-y-0.5">
              <li>Tables truncated: {result.tables_truncated}</li>
              <li>Qdrant cleared: {result.qdrant_cleared.length > 0 ? result.qdrant_cleared.join(', ') : 'skipped'}</li>
              <li>Agents seeded: {result.agents_seeded}</li>
            </ul>
          </div>
        )}

        {error && (
          <div className="p-3 rounded-lg text-sm bg-red-50 text-red-700">
            <p className="font-medium">Error: {error}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
