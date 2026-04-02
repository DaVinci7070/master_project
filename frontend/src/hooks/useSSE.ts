'use client'

import { useEffect, useState, useRef } from 'react'

interface SSEOptions<T> {
  onMessage?: (data: T) => void
  onError?: (error: Error) => void
  enabled?: boolean
  eventTypes?: string[]  // Named event types to listen for
}

export function useSSE<T>(url: string, options: SSEOptions<T> = {}) {
  const { onMessage, onError, enabled = true, eventTypes } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isConnected, setIsConnected] = useState(false)

  // Use refs to avoid stale closure issues
  const onMessageRef = useRef(onMessage)
  const onErrorRef = useRef(onError)
  onMessageRef.current = onMessage
  onErrorRef.current = onError

  useEffect(() => {
    if (!enabled) return

    const eventSource = new EventSource(url)

    eventSource.onopen = () => {
      setIsConnected(true)
      setError(null)
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
      eventSource.addEventListener(eventType, handleEvent)
    })

    eventSource.onerror = () => {
      const connectionError = new Error('SSE connection failed')
      setError(connectionError)
      setIsConnected(false)
      onErrorRef.current?.(connectionError)
      eventSource.close()
    }

    return () => {
      eventsToListen.forEach((eventType) => {
        eventSource.removeEventListener(eventType, handleEvent)
      })
      eventSource.close()
      setIsConnected(false)
    }
  }, [url, enabled, eventTypes])

  return { data, error, isConnected }
}
