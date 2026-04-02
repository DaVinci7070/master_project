'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { executeChallenge, fetchBuildPlan } from '@/lib/api'
import { BuildPlanDisplay } from './build-plan-display'
import type { ChallengeAnalysisResponse, CapabilityGap, ConfidenceLevel, GapSeverity, BuildPlan, BuildPlanStatus } from '@/types'

interface AssessmentResultProps {
  response: ChallengeAnalysisResponse
  onExecuteStart?: () => void
  onBuildComplete?: () => void
}

const confidenceColors: Record<ConfidenceLevel, string> = {
  CAN_DO: 'bg-green-100 text-green-800 border-green-300',
  MAYBE: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  CANNOT_DO: 'bg-red-100 text-red-800 border-red-300',
}

const confidenceLabels: Record<ConfidenceLevel, string> = {
  CAN_DO: 'Can Do',
  MAYBE: 'Maybe',
  CANNOT_DO: 'Cannot Do',
}

const severityColors: Record<GapSeverity, string> = {
  critical: 'bg-red-100 text-red-700',
  important: 'bg-orange-100 text-orange-700',
  minor: 'bg-gray-100 text-gray-700',
}

function GapBadge({ gap }: { gap: CapabilityGap }) {
  const gapTypeLabel = gap.gap_type.split('_').map(word =>
    word.charAt(0).toUpperCase() + word.slice(1)
  ).join(' ')

  return (
    <div className={`p-3 rounded-lg ${severityColors[gap.severity]}`}>
      <div className="flex items-center justify-between">
        <span className="font-medium text-sm">{gapTypeLabel}</span>
        <span className="text-xs px-2 py-0.5 rounded bg-white/50 capitalize">{gap.severity}</span>
      </div>
      <p className="text-sm mt-1">{gap.description}</p>
      <p className="text-xs mt-1 opacity-75">Affects: {gap.affected_capability}</p>
      {gap.occurrence_count > 1 && (
        <p className="text-xs mt-1 opacity-75">Occurred {gap.occurrence_count} times</p>
      )}
    </div>
  )
}

export function AssessmentResult({ response, onExecuteStart, onBuildComplete }: AssessmentResultProps) {
  const router = useRouter()
  const [isExecuting, setIsExecuting] = useState(false)
  const [executeError, setExecuteError] = useState<string | null>(null)
  const [buildPlan, setBuildPlan] = useState<BuildPlan | null>(response.build_plan || null)
  const [buildPlanStatus, setBuildPlanStatus] = useState<BuildPlanStatus>(
    (response.build_plan_status as BuildPlanStatus) || 'pending'
  )
  const [autoApplyEnabled, setAutoApplyEnabled] = useState(response.auto_apply_enabled || false)

  const { challenge_id, assessment, route_decision, analyzed_at, execution_id } = response
  const { confidence, reasoning, top_factors, gaps, improvement_suggestions, similar_past_success } = assessment

  // Poll for build plan status when in progress
  useEffect(() => {
    if (buildPlanStatus !== 'in_progress' && buildPlanStatus !== 'approved') return

    const pollInterval = setInterval(async () => {
      try {
        const planResponse = await fetchBuildPlan(challenge_id)
        setBuildPlanStatus(planResponse.status)

        if (planResponse.status === 'completed') {
          clearInterval(pollInterval)
          onBuildComplete?.()
        } else if (planResponse.status === 'failed') {
          clearInterval(pollInterval)
        }
      } catch (error) {
        console.error('Failed to poll build plan status:', error)
      }
    }, 3000)

    return () => clearInterval(pollInterval)
  }, [buildPlanStatus, challenge_id, onBuildComplete])

  async function handleExecute() {
    setIsExecuting(true)
    setExecuteError(null)
    onExecuteStart?.()

    try {
      await executeChallenge(challenge_id)
      // Navigate to execution detail page
      router.push(`/execution/${execution_id}`)
    } catch (err) {
      setExecuteError(err instanceof Error ? err.message : 'Failed to start execution')
      setIsExecuting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Capability Assessment</CardTitle>
          <span className="text-sm text-gray-500">
            {new Date(analyzed_at).toLocaleString()}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Confidence badge */}
        <div className="flex items-center gap-4">
          <span
            className={`px-4 py-2 rounded-lg border font-semibold ${confidenceColors[confidence]}`}
          >
            {confidenceLabels[confidence]}
          </span>
          <span className="text-gray-600">{reasoning}</span>
        </div>

        {/* Route decision */}
        <div className="flex items-center gap-2 text-sm">
          <span className="text-gray-500">Route:</span>
          <span className={`font-medium ${
            route_decision === 'execute' ? 'text-green-600' : 'text-indigo-600'
          }`}>
            {route_decision === 'execute' ? 'Proceed to Execution' : 'Route to Developer Team'}
          </span>
        </div>

        {/* Top factors */}
        {top_factors.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-gray-700 mb-2">Key Factors</h4>
            <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
              {top_factors.map((factor, i) => (
                <li key={i}>{factor}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Capability gaps */}
        {gaps.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-gray-700 mb-2">
              Capability Gaps ({gaps.length})
            </h4>
            <div className="space-y-2">
              {gaps.map((gap, i) => (
                <GapBadge key={i} gap={gap} />
              ))}
            </div>
          </div>
        )}

        {/* Improvement suggestions */}
        {improvement_suggestions.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-gray-700 mb-2">Suggestions</h4>
            <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
              {improvement_suggestions.map((suggestion, i) => (
                <li key={i}>{suggestion}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Past success indicator */}
        {similar_past_success && (
          <div className="flex items-center gap-2 text-sm text-green-600">
            <span className="w-2 h-2 bg-green-500 rounded-full" />
            Similar challenge was successful in the past
          </div>
        )}

        {/* Execute button - shown when route_decision is 'execute' */}
        {route_decision === 'execute' && (
          <div className="pt-4 border-t">
            {executeError && (
              <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                {executeError}
              </div>
            )}
            <Button
              onClick={handleExecute}
              disabled={isExecuting}
              className="w-full"
              size="lg"
            >
              {isExecuting ? (
                <>
                  <span className="animate-spin mr-2">&#9696;</span>
                  Starting Execution...
                </>
              ) : (
                'Execute Challenge'
              )}
            </Button>
          </div>
        )}

        {/* Build Plan - shown when route_decision is 'developer_team' */}
        {route_decision === 'developer_team' && buildPlan && (
          <div className="pt-4 border-t">
            <BuildPlanDisplay
              challengeId={challenge_id}
              plan={buildPlan}
              status={buildPlanStatus}
              autoApplyEnabled={autoApplyEnabled}
              onApproved={() => {
                setBuildPlanStatus('approved')
              }}
              onRejected={() => {
                setBuildPlanStatus('rejected')
              }}
            />

            {/* Execute button after build completed */}
            {buildPlanStatus === 'completed' && (
              <div className="mt-4">
                <Button
                  onClick={handleExecute}
                  disabled={isExecuting}
                  className="w-full bg-green-600 hover:bg-green-700"
                  size="lg"
                >
                  {isExecuting ? (
                    <>
                      <span className="animate-spin mr-2">&#9696;</span>
                      Starting Execution...
                    </>
                  ) : (
                    'Capabilities gebaut - Jetzt ausführen'
                  )}
                </Button>
              </div>
            )}
          </div>
        )}

        {/* No build plan but developer_team route */}
        {route_decision === 'developer_team' && !buildPlan && (
          <div className="pt-4 border-t">
            <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-800">
              <p className="font-medium">Capabilities fehlen</p>
              <p className="text-sm mt-1">
                Das System analysiert die fehlenden Capabilities. Ein Build-Plan wird erstellt...
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
