'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { TestResults } from './test-results'
import { SkillDetailDialog } from './skill-detail-dialog'
import type { Skill } from '@/types'
import { useState } from 'react'
import { updateSkill } from '@/lib/api'

interface SkillCardProps {
  skill: Skill
  onUpdated?: (skill: Skill) => void
}

export function SkillCard({ skill, onUpdated }: SkillCardProps) {
  const [codeOpen, setCodeOpen] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editData, setEditData] = useState({
    applicability: skill.applicability ?? '',
    instructions: skill.instructions ?? '',
    termination: skill.termination ?? '',
  })

  const isPlanning = skill.skill_type === 'planning'

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

  async function handleSave() {
    setSaving(true)
    try {
      const updated = await updateSkill(skill.id, editData)
      setEditing(false)
      onUpdated?.(updated)
    } catch (e) {
      console.error('Failed to update skill:', e)
    } finally {
      setSaving(false)
    }
  }

  function handleCancel() {
    setEditData({
      applicability: skill.applicability ?? '',
      instructions: skill.instructions ?? '',
      termination: skill.termination ?? '',
    })
    setEditing(false)
  }

  return (
    <Card className={skill.is_active ? '' : 'opacity-60'}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-base">{skill.name}</CardTitle>
            <span
              className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                isPlanning
                  ? 'bg-purple-100 text-purple-700'
                  : 'bg-blue-100 text-blue-700'
              }`}
            >
              {isPlanning ? 'Planning' : 'Functional'}
            </span>
          </div>
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

        {/* Applicability */}
        {skill.applicability && !editing && (
          <div className="text-sm">
            <span className="font-medium text-gray-500">Applicability: </span>
            <span className="text-gray-600">{skill.applicability}</span>
          </div>
        )}

        {/* Planning skill: show instructions instead of code */}
        {isPlanning && !editing && skill.instructions && (
          <Collapsible>
            <CollapsibleTrigger className="text-sm text-purple-600 hover:text-purple-700">
              View instructions
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2">
              <pre className="text-xs bg-gray-50 text-gray-800 p-3 rounded-lg whitespace-pre-wrap">
                {skill.instructions}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Inline edit for planning skills */}
        {isPlanning && editing && (
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-gray-500">Applicability</label>
              <textarea
                className="w-full mt-1 text-sm border rounded-lg p-2 min-h-[60px]"
                value={editData.applicability}
                onChange={(e) => setEditData({ ...editData, applicability: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500">Instructions</label>
              <textarea
                className="w-full mt-1 text-sm border rounded-lg p-2 min-h-[100px]"
                value={editData.instructions}
                onChange={(e) => setEditData({ ...editData, instructions: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500">Termination</label>
              <textarea
                className="w-full mt-1 text-sm border rounded-lg p-2 min-h-[60px]"
                value={editData.termination}
                onChange={(e) => setEditData({ ...editData, termination: e.target.value })}
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={handleCancel}
                className="px-3 py-1 text-sm bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Edit button for planning skills */}
        {isPlanning && !editing && (
          <button
            onClick={() => setEditing(true)}
            className="text-sm text-purple-600 hover:text-purple-700"
          >
            Edit
          </button>
        )}

        {/* Test Results */}
        <TestResults testCases={skill.test_cases || []} />

        {/* Code Preview - only for functional skills */}
        {!isPlanning && skill.code && (
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
          <div className="flex items-center gap-2">
            <span>ID: {skill.id.slice(0, 8)}</span>
            {skill.parent_id && (
              <span>from: {skill.parent_id.slice(0, 8)}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span>{new Date(skill.created_at).toLocaleDateString()}</span>
            <button
              onClick={() => setDetailOpen(true)}
              className="text-indigo-600 hover:text-indigo-700 font-medium"
            >
              Details
            </button>
          </div>
        </div>

        <SkillDetailDialog
          skillId={skill.id}
          skillName={skill.name}
          open={detailOpen}
          onOpenChange={setDetailOpen}
        />
      </CardContent>
    </Card>
  )
}