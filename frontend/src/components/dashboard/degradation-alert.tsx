'use client'

import { useEffect, useState } from 'react'
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
import { fetchTelemetrySummary, triggerEmergencyStop } from '@/lib/api'
import type { TelemetrySummary } from '@/types'

interface DegradationAlertProps {
  checkInterval?: number // ms
  degradationThreshold?: number // percentage
}

interface Degradation {
  metric: string
  current: number
  baseline: number
  change: number
}

export function DegradationAlert({
  checkInterval = 30000, // 30 seconds
  degradationThreshold = 10, // 10%
}: DegradationAlertProps) {
  const [baseline, setBaseline] = useState<TelemetrySummary | null>(null)
  const [degradations, setDegradations] = useState<Degradation[]>([])
  const [alertOpen, setAlertOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    // Capture baseline on mount
    async function captureBaseline() {
      try {
        const data = await fetchTelemetrySummary()
        setBaseline(data)
      } catch (error) {
        console.error('Failed to capture baseline:', error)
      }
    }
    captureBaseline()
  }, [])

  useEffect(() => {
    if (!baseline) return

    const checkDegradation = async () => {
      try {
        const current = await fetchTelemetrySummary()

        const detected: Degradation[] = []

        // Check success rate degradation
        if (baseline.success_rate_overall > 0) {
          const successChange = ((baseline.success_rate_overall - current.success_rate_overall) / baseline.success_rate_overall) * 100
          if (successChange > degradationThreshold) {
            detected.push({
              metric: 'Success Rate',
              current: current.success_rate_overall,
              baseline: baseline.success_rate_overall,
              change: successChange,
            })
          }
        }

        // Check latency degradation (increase)
        if (baseline.avg_latency_ms && current.avg_latency_ms) {
          const latencyChange = ((current.avg_latency_ms - baseline.avg_latency_ms) / baseline.avg_latency_ms) * 100
          if (latencyChange > degradationThreshold) {
            detected.push({
              metric: 'Average Latency',
              current: current.avg_latency_ms,
              baseline: baseline.avg_latency_ms,
              change: latencyChange,
            })
          }
        }

        // Check error rate increase
        const baselineErrorRate = 100 - baseline.success_rate_overall
        const currentErrorRate = 100 - current.success_rate_overall
        if (baselineErrorRate > 0) {
          const errorChange = ((currentErrorRate - baselineErrorRate) / baselineErrorRate) * 100
          if (errorChange > degradationThreshold) {
            detected.push({
              metric: 'Error Rate',
              current: currentErrorRate,
              baseline: baselineErrorRate,
              change: errorChange,
            })
          }
        }

        if (detected.length > 0) {
          setDegradations(detected)
          setAlertOpen(true)
        }
      } catch (error) {
        console.error('Failed to check degradation:', error)
      }
    }

    const interval = setInterval(checkDegradation, checkInterval)
    return () => clearInterval(interval)
  }, [baseline, checkInterval, degradationThreshold])

  async function handleEmergencyStop() {
    setLoading(true)
    try {
      await triggerEmergencyStop()
      setAlertOpen(false)
      // Reset baseline after stop
      const newBaseline = await fetchTelemetrySummary()
      setBaseline(newBaseline)
    } catch (error) {
      console.error('Emergency stop failed:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AlertDialog open={alertOpen} onOpenChange={setAlertOpen}>
      <AlertDialogContent className="border-red-200">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-red-600 flex items-center gap-2">
            <span className="animate-pulse">⚠</span>
            Metric Degradation Detected
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-4">
              <p>
                One or more core metrics have degraded by more than {degradationThreshold}%.
                Consider triggering an emergency stop to rollback to the last stable version.
              </p>

              <div className="space-y-2">
                {degradations.map((d, i) => (
                  <div key={i} className="flex items-center justify-between p-2 bg-red-50 rounded">
                    <span className="font-medium">{d.metric}</span>
                    <div className="text-right">
                      <span className="text-red-600 font-semibold">
                        {d.change.toFixed(1)}% degradation
                      </span>
                      <div className="text-xs text-gray-500">
                        {d.baseline.toFixed(1)} → {d.current.toFixed(1)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={loading}>
            Dismiss (Monitor)
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleEmergencyStop}
            className="bg-red-600 hover:bg-red-700"
            disabled={loading}
          >
            {loading ? 'Stopping...' : 'Emergency Stop & Rollback'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
