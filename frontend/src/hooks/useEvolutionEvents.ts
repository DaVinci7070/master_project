'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchEvolutionHistory } from '@/lib/api'
import type { EvolutionEvent } from '@/types'

interface UseEvolutionEventsOptions {
  executionId?: string
  limit?: number
  /** Poll interval in ms. Defaults to 3000. Set to 0 to disable polling. */
  intervalMs?: number
  enabled?: boolean
}

interface UseEvolutionEventsResult {
  events: EvolutionEvent[]
  loading: boolean
  error: Error | null
  lastUpdated: Date | null
  refresh: () => Promise<void>
}

/**
 * Polls GET /api/v1/evolution/history on a fixed cadence.
 *
 * SSE is an optional Phase-2 upgrade per the roadmap (Track 2 §3.2.4);
 * polling keeps Sprint 3 dependency-free and good enough for the
 * ~3 s UI-freshness target.
 */
export function useEvolutionEvents(
  options: UseEvolutionEventsOptions = {}
): UseEvolutionEventsResult {
  const { executionId, limit = 200, intervalMs = 3000, enabled = true } = options

  const [events, setEvents] = useState<EvolutionEvent[]>([])
  const [loading, setLoading] = useState<boolean>(enabled)
  const [error, setError] = useState<Error | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  // Guard against races / stale fetches after unmount.
  const mountedRef = useRef<boolean>(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const load = useCallback(async () => {
    try {
      const data = await fetchEvolutionHistory(executionId, limit)
      if (!mountedRef.current) return
      setEvents(data.events)
      setLastUpdated(new Date())
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [executionId, limit])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }

    setLoading(true)
    void load()

    if (intervalMs <= 0) return
    const handle = window.setInterval(() => {
      void load()
    }, intervalMs)
    return () => window.clearInterval(handle)
  }, [enabled, intervalMs, load])

  return { events, loading, error, lastUpdated, refresh: load }
}
