'use client'

import { useState } from 'react'
import { ChallengeInput, AssessmentResult } from '@/components/execution'
import type { ChallengeAnalysisResponse } from '@/types'

export default function ExecutionPage() {
  const [response, setResponse] = useState<ChallengeAnalysisResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(res: ChallengeAnalysisResponse) {
    setResponse(res)
    setError(null)
  }

  function handleError(err: Error) {
    setError(err.message)
    setResponse(null)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Challenge Execution</h1>
        <p className="text-gray-500 mt-1">Submit a challenge for the system to analyze and execute</p>
      </div>

      <ChallengeInput onSubmit={handleSubmit} onError={handleError} />

      {/* Error display */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          {error}
        </div>
      )}

      {/* Assessment result */}
      {response && <AssessmentResult response={response} />}
    </div>
  )
}
