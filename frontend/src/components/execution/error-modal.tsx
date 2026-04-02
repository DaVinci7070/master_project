'use client'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

interface ErrorModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  error: string
  executionId: string
  onRetry: () => void
  onViewLogs: () => void
  onDismiss: () => void
}

export function ErrorModal({
  open,
  onOpenChange,
  error,
  executionId,
  onRetry,
  onViewLogs,
  onDismiss,
}: ErrorModalProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="text-red-600">Execution Error</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3">
              <p>The execution encountered an error and has stopped.</p>
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                {error}
              </div>
              <p className="text-xs text-gray-500">
                Execution ID: {executionId.slice(0, 8)}
              </p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="flex-col sm:flex-row gap-2">
          <AlertDialogCancel onClick={onDismiss}>
            Dismiss
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onViewLogs}
            className="bg-gray-900 hover:bg-gray-800"
          >
            View Logs
          </AlertDialogAction>
          <AlertDialogAction
            onClick={onRetry}
            className="bg-indigo-600 hover:bg-indigo-700"
          >
            Retry Execution
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
