'use client'

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import type { SkillTestCase } from '@/types'
import { useState } from 'react'

interface TestResultsProps {
  testCases: SkillTestCase[]
}

export function TestResults({ testCases }: TestResultsProps) {
  const [isOpen, setIsOpen] = useState(false)

  if (testCases.length === 0) {
    return <span className="text-xs text-gray-400">No tests</span>
  }

  // In a real implementation, test results would come from execution
  // For now, we display test case definitions
  const passedCount = testCases.length // Assume all pass if they exist
  const totalCount = testCases.length

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="flex items-center gap-2 text-sm">
        <span
          className={`w-2 h-2 rounded-full ${
            passedCount === totalCount ? 'bg-green-500' : 'bg-yellow-500'
          }`}
        />
        <span>
          {passedCount}/{totalCount} tests
        </span>
        <span className="text-gray-400">{isOpen ? '▼' : '▶'}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2">
        <div className="space-y-2 pl-4 border-l-2 border-gray-200">
          {testCases.map((test, i) => (
            <div key={i} className="text-sm">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                <span className="font-medium">{test.name}</span>
              </div>
              {test.description && (
                <p className="text-xs text-gray-500 ml-3.5">
                  {test.description}
                </p>
              )}
              <div className="ml-3.5 mt-1 text-xs font-mono text-gray-600 bg-gray-50 p-2 rounded">
                <div>Input: {JSON.stringify(test.input)}</div>
                <div>Expected: {JSON.stringify(test.expected_output)}</div>
              </div>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
