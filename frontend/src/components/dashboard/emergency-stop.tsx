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
import { triggerEmergencyStop } from '@/lib/api'

interface EmergencyStopProps {
  onTriggered?: () => void
}

export function EmergencyStop({ onTriggered }: EmergencyStopProps) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)

  async function handleEmergencyStop() {
    setLoading(true)
    try {
      const response = await triggerEmergencyStop()
      setResult(response)
      onTriggered?.()
    } catch (error) {
      setResult({
        success: false,
        message: error instanceof Error ? error.message : 'Failed to trigger emergency stop',
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="destructive"
          size="lg"
          className="shadow-lg hover:shadow-xl transition-shadow"
        >
          <span className="mr-2">⚠</span>
          Emergency Stop
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="text-red-600 flex items-center gap-2">
            <span className="text-2xl">⚠</span>
            Emergency Stop
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-4">
              <p>This will immediately:</p>
              <ul className="list-disc list-inside space-y-1 text-sm">
                <li><strong>Halt all Developer Team operations</strong></li>
                <li><strong>Cancel any running capability builds</strong></li>
                <li><strong>Roll back to the last stable version</strong></li>
                <li><strong>Deactivate any provisional changes</strong></li>
              </ul>
              <p className="text-sm text-gray-500">
                This action cannot be undone. The system will return to its last known stable state.
              </p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        {result && (
          <div className={`p-3 rounded-lg ${
            result.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
          }`}>
            {result.message}
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={loading}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleEmergencyStop}
            className="bg-red-600 hover:bg-red-700"
            disabled={loading}
          >
            {loading ? 'Stopping...' : 'Yes, Emergency Stop'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
