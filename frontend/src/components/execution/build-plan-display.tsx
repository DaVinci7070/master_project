'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { approveBuildPlan, type BuildPlan, type BuildPlanResponse } from '@/lib/api'
import {
  Wrench,
  FileText,
  Bot,
  Network,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'

interface BuildPlanDisplayProps {
  challengeId: string
  plan: BuildPlan
  status: BuildPlanResponse['status']
  autoApplyEnabled: boolean
  onApproved?: () => void
  onRejected?: () => void
}

const actionIcons = {
  create_skill: Wrench,
  improve_prompt: FileText,
  create_agent: Bot,
  update_topology: Network,
}

const actionLabels = {
  create_skill: 'Skill erstellen',
  improve_prompt: 'Prompt verbessern',
  create_agent: 'Agent erstellen',
  update_topology: 'Topologie aktualisieren',
}

const complexityColors = {
  low: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  high: 'bg-red-100 text-red-700',
}

const severityColors = {
  critical: 'bg-red-100 text-red-700 border-red-300',
  important: 'bg-orange-100 text-orange-700 border-orange-300',
  minor: 'bg-blue-100 text-blue-700 border-blue-300',
}

export function BuildPlanDisplay({
  challengeId,
  plan,
  status,
  autoApplyEnabled,
  onApproved,
  onRejected,
}: BuildPlanDisplayProps) {
  const [isExpanded, setIsExpanded] = useState(true)
  const [isProcessing, setIsProcessing] = useState(false)
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [currentStatus, setCurrentStatus] = useState(status)

  // Sync status prop to local state when parent updates it from polling
  useEffect(() => {
    setCurrentStatus(status)
  }, [status])

  async function handleApprove() {
    setIsProcessing(true)
    try {
      await approveBuildPlan(challengeId, true)
      setCurrentStatus('approved')
      onApproved?.()
    } catch (error) {
      console.error('Failed to approve plan:', error)
    } finally {
      setIsProcessing(false)
    }
  }

  async function handleReject() {
    if (!showFeedback) {
      setShowFeedback(true)
      return
    }

    setIsProcessing(true)
    try {
      await approveBuildPlan(challengeId, false, feedback || undefined)
      setCurrentStatus('rejected')
      onRejected?.()
    } catch (error) {
      console.error('Failed to reject plan:', error)
    } finally {
      setIsProcessing(false)
    }
  }

  const isPending = currentStatus === 'pending'
  const isInProgress = currentStatus === 'in_progress' || currentStatus === 'approved'
  const isCompleted = currentStatus === 'completed'
  const isFailed = currentStatus === 'failed'
  const isRejected = currentStatus === 'rejected'

  return (
    <Card className={`border-2 ${
      isPending ? 'border-blue-300 bg-blue-50/50' :
      isInProgress ? 'border-yellow-300 bg-yellow-50/50' :
      isCompleted ? 'border-green-300 bg-green-50/50' :
      isFailed ? 'border-red-300 bg-red-50/50' :
      isRejected ? 'border-gray-300 bg-gray-50/50' :
      'border-gray-200'
    }`}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
              isPending ? 'bg-blue-500' :
              isInProgress ? 'bg-yellow-500' :
              isCompleted ? 'bg-green-500' :
              isFailed ? 'bg-red-500' :
              'bg-gray-500'
            }`}>
              {isInProgress ? (
                <Loader2 className="w-5 h-5 text-white animate-spin" />
              ) : isCompleted ? (
                <CheckCircle className="w-5 h-5 text-white" />
              ) : isFailed || isRejected ? (
                <XCircle className="w-5 h-5 text-white" />
              ) : (
                <Wrench className="w-5 h-5 text-white" />
              )}
            </div>
            <div>
              <CardTitle className="text-lg">Build-Plan</CardTitle>
              <CardDescription>
                {plan.total_gaps} Gaps erkannt, {plan.critical_gaps} kritisch
              </CardDescription>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {autoApplyEnabled && isPending && (
              <Badge className="bg-yellow-500">Auto-Apply aktiv</Badge>
            )}

            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsExpanded(!isExpanded)}
            >
              {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </Button>
          </div>
        </div>
      </CardHeader>

      {isExpanded && (
        <>
          <CardContent className="space-y-4">
            {/* Status message */}
            {isInProgress && (
              <div className="flex items-center gap-2 p-3 bg-yellow-100 rounded-lg text-yellow-800">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Capabilities werden gebaut...</span>
              </div>
            )}

            {isCompleted && (
              <div className="flex items-center gap-2 p-3 bg-green-100 rounded-lg text-green-800">
                <CheckCircle className="w-4 h-4" />
                <span>Alle Capabilities erfolgreich gebaut! System bereit zur Ausführung.</span>
              </div>
            )}

            {isFailed && (
              <div className="flex items-center gap-2 p-3 bg-red-100 rounded-lg text-red-800">
                <AlertTriangle className="w-4 h-4" />
                <span>Capability-Building fehlgeschlagen. Bitte manuell prüfen.</span>
              </div>
            )}

            {/* Plan items */}
            <div className="space-y-2">
              <h4 className="font-medium text-sm text-gray-600">Geplante Aktionen:</h4>
              {plan.items.map((item, idx) => {
                const Icon = actionIcons[item.action_type]
                return (
                  <div
                    key={idx}
                    className={`flex items-start gap-3 p-3 rounded-lg border ${
                      severityColors[item.gap_severity as keyof typeof severityColors] || 'bg-gray-50 border-gray-200'
                    }`}
                  >
                    <Icon className="w-5 h-5 mt-0.5 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium">{actionLabels[item.action_type]}</span>
                        <Badge variant="outline" className={complexityColors[item.estimated_complexity]}>
                          {item.estimated_complexity}
                        </Badge>
                      </div>
                      <p className="text-sm text-gray-600 mt-1">{item.description}</p>
                      <p className="text-xs text-gray-500 mt-1">
                        Ziel: {item.target_capability}
                      </p>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Expected outcome */}
            <div className="p-3 bg-white rounded-lg border border-gray-200">
              <p className="text-sm">
                <span className="font-medium">Nach Build:</span>{' '}
                <span className="text-green-600">{plan.confidence_after_build}</span>
              </p>
            </div>

            {/* Feedback textarea for rejection */}
            {showFeedback && isPending && (
              <div className="space-y-2">
                <label className="text-sm font-medium text-gray-700">
                  Feedback (optional):
                </label>
                <Textarea
                  placeholder="Warum lehnen Sie den Plan ab?"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  rows={3}
                />
              </div>
            )}
          </CardContent>

          {/* Actions - always show when pending */}
          {isPending && (
            <CardFooter className="flex justify-end gap-2 pt-0">
              <Button
                variant="outline"
                onClick={handleReject}
                disabled={isProcessing}
              >
                {showFeedback ? 'Ablehnung bestätigen' : 'Ablehnen'}
              </Button>
              <Button
                onClick={handleApprove}
                disabled={isProcessing}
                className="bg-blue-600 hover:bg-blue-700"
                size="lg"
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Wird verarbeitet...
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-4 h-4 mr-2" />
                    Genehmigen & Bauen
                  </>
                )}
              </Button>
            </CardFooter>
          )}
        </>
      )}
    </Card>
  )
}
