'use client'

import { useState, useEffect } from 'react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface LogEntry {
  timestamp: string
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
  agentId?: string
}

interface ExecutionLogsProps {
  logs: LogEntry[]
  forceOpen?: boolean
}

const levelColors = {
  info: 'text-gray-600',
  warn: 'text-yellow-600',
  error: 'text-red-600',
  debug: 'text-gray-400',
}

export function ExecutionLogs({ logs, forceOpen }: ExecutionLogsProps) {
  const [isOpen, setIsOpen] = useState(false) // Hidden by default per CONTEXT

  useEffect(() => {
    if (forceOpen) setIsOpen(true)
  }, [forceOpen])

  return (
    <Card>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CardHeader className="cursor-pointer" onClick={() => setIsOpen(!isOpen)}>
          <CollapsibleTrigger asChild>
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg">Execution Logs</CardTitle>
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-500">{logs.length} entries</span>
                <span className="text-gray-400">{isOpen ? '▼' : '▶'}</span>
              </div>
            </div>
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent>
          <CardContent>
            <div className="bg-gray-900 rounded-lg p-4 max-h-[400px] overflow-y-auto">
              {logs.length === 0 ? (
                <p className="text-gray-500 text-sm">No logs yet</p>
              ) : (
                <div className="space-y-1 font-mono text-xs">
                  {logs.map((log, i) => (
                    <div key={i} className="flex gap-2">
                      <span className="text-gray-500 shrink-0">
                        {new Date(log.timestamp).toLocaleTimeString()}
                      </span>
                      <span className={`shrink-0 ${levelColors[log.level]}`}>
                        [{log.level.toUpperCase()}]
                      </span>
                      {log.agentId && (
                        <span className="text-indigo-400 shrink-0">[{log.agentId}]</span>
                      )}
                      <span className="text-gray-300">{log.message}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
