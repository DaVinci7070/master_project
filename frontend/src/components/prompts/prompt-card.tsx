'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { fetchPrompt } from '@/lib/api'
import type { Prompt } from '@/types'

interface PromptCardProps {
  prompt: Prompt
  onViewHistory?: () => void
}

export function PromptCard({ prompt, onViewHistory }: PromptCardProps) {
  const [fullContent, setFullContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleOpen(open: boolean) {
    if (open && fullContent === null) {
      setLoading(true)
      try {
        const full = await fetchPrompt(prompt.id)
        setFullContent(full.content ?? '')
      } catch {
        setFullContent('Failed to load prompt content.')
      } finally {
        setLoading(false)
      }
    }
  }

  return (
    <Card className={prompt.is_active ? '' : 'opacity-60'}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">{prompt.name}</CardTitle>
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              prompt.is_active
                ? 'bg-green-100 text-green-700'
                : 'bg-gray-100 text-gray-500'
            }`}
          >
            {prompt.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Metadata */}
        {prompt.prompt_metadata && Object.keys(prompt.prompt_metadata).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(prompt.prompt_metadata).slice(0, 3).map(([key, value]) => (
              <span
                key={key}
                className="text-xs px-2 py-1 bg-gray-100 text-gray-600 rounded"
              >
                {key}: {String(value).slice(0, 20)}
              </span>
            ))}
          </div>
        )}

        {/* Content Preview */}
        <Dialog onOpenChange={handleOpen}>
          <DialogTrigger className="text-sm text-indigo-600 hover:text-indigo-700">
            View content
          </DialogTrigger>
          <DialogContent className="sm:max-w-3xl max-h-[85vh] flex flex-col">
            <DialogHeader>
              <DialogTitle>{prompt.name}</DialogTitle>
            </DialogHeader>
            {loading ? (
              <div className="flex items-center justify-center py-12 text-gray-500">
                Loading...
              </div>
            ) : (
              <pre className="text-sm bg-gray-100 p-4 rounded-lg whitespace-pre-wrap overflow-y-auto flex-1 max-h-[70vh]">
                {fullContent}
              </pre>
            )}
            <DialogFooter showCloseButton />
          </DialogContent>
        </Dialog>

        {/* Version History Link */}
        {prompt.parent_id && (
          <button
            onClick={onViewHistory}
            className="text-sm text-gray-500 hover:text-indigo-600"
          >
            View version history
          </button>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between text-xs text-gray-400 pt-2 border-t">
          <span>ID: {prompt.id.slice(0, 8)}</span>
          <span>{new Date(prompt.created_at).toLocaleDateString()}</span>
        </div>
      </CardContent>
    </Card>
  )
}
