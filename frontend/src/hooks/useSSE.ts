'use client'

import { useEffect, useState, useRef, useCallback } from 'react'

interface SSEOptions<T> {
  onMessage?: (data: T) => void
  onError?: (error: Error) => void
  enabled?: boolean
  eventTypes?: string[]  // Named event types to listen for
  maxRetries?: number
}

export function useSSE<T>(url: string, options: SSEOptions<T> = {}) {
  const { onMessage, onError, enabled = true, eventTypes, maxRetries = 5 } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isConnected, setIsConnected] = useState(false)

  // Use refs to avoid stale closure issues
  const onMessageRef = useRef(onMessage)
  const onErrorRef = useRef(onError)
  const retriesRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout>>()
  onMessageRef.current = onMessage
  onErrorRef.current = onError

  // Reset retries when url or enabled changes
  useEffect(() => {
    retriesRef.current = 0
  }, [url, enabled])

  useEffect(() => {
    if (!enabled) return

    let eventSource: EventSource | null = null
    let cancelled = false

    function connect() {
      if (cancelled) return
      eventSource = new EventSource(url)

      eventSource.onopen = () => {
        setIsConnected(true)
        setError(null)
        retriesRef.current = 0  // Reset on successful connection
      }

      // Handler for processing events
      const handleEvent = (event: MessageEvent) => {
        try {
          const parsed = JSON.parse(event.data) as T
          setData(parsed)
          onMessageRef.current?.(parsed)
        } catch (err) {
          const parseError = new Error('Failed to parse SSE data')
          setError(parseError)
          onErrorRef.current?.(parseError)
        }
      }

      // Default message handler
      eventSource.onmessage = handleEvent

      // Listen for named events if specified
      const defaultEventTypes = ['start', 'progress', 'complete', 'error', 'heartbeat']
      const eventsToListen = eventTypes || defaultEventTypes

      eventsToListen.forEach((eventType) => {
        eventSource!.addEventListener(eventType, handleEvent)
      })

      eventSource.onerror = () => {
        eventSource?.close()
        setIsConnected(false)

        if (cancelled) return

        if (retriesRef.current < maxRetries) {
          // Exponential backoff: 1s, 2s, 4s, 8s, 16s
          const delay = Math.min(1000 * 2 ** retriesRef.current, 16000)
          retriesRef.current += 1
          retryTimerRef.current = setTimeout(connect, delay)
        } else {
          const connectionError = new Error('SSE connection failed after retries')
          setError(connectionError)
          onErrorRef.current?.(connectionError)
        }
      }
    }

    connect()

    return () => {
      cancelled = true
      clearTimeout(retryTimerRef.current)
      eventSource?.close()
      setIsConnected(false)
    }
  }, [url, enabled, eventTypes, maxRetries])

  return { data, error, isConnected }
}
