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
import { triggerSystemReset } from '@/lib/api'

interface SystemResetProps {
  onReset?: () => void
}

export function SystemReset({ onReset }: SystemResetProps) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{
    success: boolean
    message: string
    deleted_agents: number
    deleted_skills: number
    deleted_prompts: number
    deleted_events: number
    remaining_default_agents: number
  } | null>(null)

  async function handleReset() {
    setLoading(true)
    try {
      const response = await triggerSystemReset()
      setResult(response)
      onReset?.()
    } catch (error) {
      setResult({
        success: false,
        message: error instanceof Error ? error.message : 'Failed to reset system',
        deleted_agents: 0,
        deleted_skills: 0,
        deleted_prompts: 0,
        deleted_events: 0,
        remaining_default_agents: 0,
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="outline"
          size="lg"
          className="border-amber-500 text-amber-600 hover:bg-amber-50 shadow-lg hover:shadow-xl transition-shadow"
        >
          <span className="mr-2">&#x21bb;</span>
          Reset System
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="text-amber-600 flex items-center gap-2">
            <span className="text-2xl">&#x21bb;</span>
            System Reset
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-4">
              <p>This will reset the system to its default state:</p>
              <ul className="list-disc list-inside space-y-1 text-sm">
                <li><strong>Delete all system-generated agents</strong></li>
                <li><strong>Delete all skills</strong></li>
                <li><strong>Remove orphaned prompts</strong></li>
                <li><strong>Clear event logs</strong></li>
                <li><strong>Re-activate all default agents</strong></li>
              </ul>
              <p className="text-sm text-gray-500">
                Default (initial) agents will be kept and re-activated.
              </p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        {result && (
          <div className={`p-3 rounded-lg text-sm space-y-1 ${
            result.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
          }`}>
            <p className="font-medium">{result.message}</p>
            {result.success && (
              <ul className="text-xs space-y-0.5">
                <li>Agents deleted: {result.deleted_agents}</li>
                <li>Skills deleted: {result.deleted_skills}</li>
                <li>Prompts deleted: {result.deleted_prompts}</li>
                <li>Events cleared: {result.deleted_events}</li>
                <li>Default agents remaining: {result.remaining_default_agents}</li>
              </ul>
            )}
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={loading}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault()
              handleReset()
            }}
            className="bg-amber-600 hover:bg-amber-700"
            disabled={loading}
          >
            {loading ? 'Resetting...' : 'Yes, Reset System'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
