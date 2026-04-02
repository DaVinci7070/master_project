'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { TestResults } from './test-results'
import type { Skill } from '@/types'
import { useState } from 'react'

interface SkillCardProps {
  skill: Skill
}

export function SkillCard({ skill }: SkillCardProps) {
  const [codeOpen, setCodeOpen] = useState(false)

  // Health status based on active state and test count
  const testCount = skill.test_count ?? skill.test_cases?.length ?? 0
  const healthStatus = !skill.is_active
    ? 'inactive'
    : testCount >= 3
      ? 'healthy'
      : testCount > 0
        ? 'warning'
        : 'unknown'

  const healthColors = {
    healthy: 'bg-green-100 text-green-700',
    warning: 'bg-yellow-100 text-yellow-700',
    inactive: 'bg-gray-100 text-gray-500',
    unknown: 'bg-gray-100 text-gray-500',
  }

  const healthLabels = {
    healthy: 'Healthy',
    warning: 'Low Coverage',
    inactive: 'Inactive',
    unknown: 'No Tests',
  }

  return (
    <Card className={skill.is_active ? '' : 'opacity-60'}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">{skill.name}</CardTitle>
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${healthColors[healthStatus]}`}
          >
            {healthLabels[healthStatus]}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Description */}
        {skill.description && (
          <p className="text-sm text-gray-600">{skill.description}</p>
        )}

        {/* Test Results */}
        <TestResults testCases={skill.test_cases || []} />

        {/* Code Preview - only if code is available */}
        {skill.code && (
          <Collapsible open={codeOpen} onOpenChange={setCodeOpen}>
            <CollapsibleTrigger className="text-sm text-indigo-600 hover:text-indigo-700">
              {codeOpen ? 'Hide code' : 'View code'}
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2">
              <pre className="text-xs bg-gray-900 text-gray-100 p-3 rounded-lg overflow-x-auto max-h-60">
                {skill.code}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Metadata */}
        <div className="flex items-center justify-between text-xs text-gray-400 pt-2 border-t">
          <span>ID: {skill.id.slice(0, 8)}</span>
          <span>{new Date(skill.created_at).toLocaleDateString()}</span>
        </div>

        {/* Version indicator */}
        {skill.parent_id && (
          <div className="text-xs text-gray-400">
            Derived from: {skill.parent_id.slice(0, 8)}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
