'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { Prompt } from '@/types'

interface PromptCardProps {
  prompt: Prompt
  onViewHistory?: () => void
}

export function PromptCard({ prompt, onViewHistory }: PromptCardProps) {
  const [contentOpen, setContentOpen] = useState(false)

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
        <Collapsible open={contentOpen} onOpenChange={setContentOpen}>
          <CollapsibleTrigger className="text-sm text-indigo-600 hover:text-indigo-700">
            {contentOpen ? 'Hide content' : 'View content'}
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2">
            <pre className="text-xs bg-gray-100 p-3 rounded-lg whitespace-pre-wrap max-h-60 overflow-y-auto">
              {prompt.content}
            </pre>
          </CollapsibleContent>
        </Collapsible>

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
