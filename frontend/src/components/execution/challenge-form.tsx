'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { submitChallenge } from '@/lib/api'
import type { ChallengeAnalysisResponse } from '@/types'

interface ChallengeFormProps {
  onSubmit: (response: ChallengeAnalysisResponse) => void
  onError: (error: Error) => void
  disabled?: boolean
}

const MAX_CHARACTERS = 10000

export function ChallengeForm({ onSubmit, onError, disabled }: ChallengeFormProps) {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!text.trim() || loading) return

    setLoading(true)
    try {
      const response = await submitChallenge(text.trim())
      onSubmit(response)
      setText('')
    } catch (error) {
      onError(error instanceof Error ? error : new Error('Failed to submit challenge'))
    } finally {
      setLoading(false)
    }
  }

  const isOverLimit = text.length > MAX_CHARACTERS
  const canSubmit = text.trim().length > 0 && !loading && !disabled && !isOverLimit

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Submit Challenge</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="challenge" className="block text-sm font-medium text-gray-700 mb-1">
              Describe the task or challenge
            </label>
            <textarea
              id="challenge"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Enter your challenge here. Be specific about what you want the system to accomplish..."
              className="w-full min-h-[150px] px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y"
              disabled={disabled || loading}
            />
          </div>
          <div className="flex justify-between items-center">
            <span className={`text-sm ${isOverLimit ? 'text-red-500 font-medium' : 'text-gray-500'}`}>
              {text.length.toLocaleString()} / {MAX_CHARACTERS.toLocaleString()} characters
            </span>
            <Button
              type="submit"
              disabled={!canSubmit}
            >
              {loading ? 'Analyzing...' : 'Submit Challenge'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
