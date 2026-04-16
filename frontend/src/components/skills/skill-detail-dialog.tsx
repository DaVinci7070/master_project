'use client'

import { useState, useEffect } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { fetchSkill } from '@/lib/api'
import type { Skill } from '@/types'

interface SkillDetailDialogProps {
  skillId: string
  skillName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SkillDetailDialog({
  skillId,
  skillName,
  open,
  onOpenChange,
}: SkillDetailDialogProps) {
  const [skill, setSkill] = useState<Skill | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open && !skill) {
      setLoading(true)
      setError(null)
      fetchSkill(skillId)
        .then(setSkill)
        .catch(() => setError('Failed to load skill details.'))
        .finally(() => setLoading(false))
    }
  }, [open, skill, skillId])

  const isPlanning = skill?.skill_type === 'planning'

  const pipReqs = skill?.skill_metadata?.pip_requirements as string[] | undefined
  const sysReqs = skill?.skill_metadata?.system_packages as string[] | undefined

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <DialogTitle>{skillName}</DialogTitle>
            {skill && (
              <span
                className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                  isPlanning
                    ? 'bg-purple-100 text-purple-700'
                    : 'bg-blue-100 text-blue-700'
                }`}
              >
                {isPlanning ? 'Planning' : 'Functional'}
              </span>
            )}
          </div>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-500">
            Loading...
          </div>
        ) : error ? (
          <div className="flex items-center justify-center py-12 text-red-500">
            {error}
          </div>
        ) : skill ? (
          <div className="overflow-y-auto flex-1 space-y-4 pr-1">
            {/* Description */}
            {skill.description && (
              <Section label="Description">
                <p className="text-sm text-gray-700">{skill.description}</p>
              </Section>
            )}

            {/* Applicability */}
            {skill.applicability && (
              <Section label="Applicability (when to use)">
                <p className="text-sm text-gray-700">{skill.applicability}</p>
              </Section>
            )}

            {/* Termination */}
            {skill.termination && (
              <Section label="Termination condition">
                <p className="text-sm text-gray-700">{skill.termination}</p>
              </Section>
            )}

            {/* Instructions (planning skills) */}
            {isPlanning && skill.instructions && (
              <Section label="Instructions">
                <pre className="text-xs bg-gray-50 text-gray-800 p-3 rounded-lg whitespace-pre-wrap">
                  {skill.instructions}
                </pre>
              </Section>
            )}

            {/* Code (functional skills) */}
            {!isPlanning && skill.code && (
              <Section label="Code">
                <pre className="text-xs bg-gray-900 text-gray-100 p-3 rounded-lg overflow-x-auto max-h-72">
                  {skill.code}
                </pre>
              </Section>
            )}

            {/* Interface */}
            {skill.interface && Object.keys(skill.interface).length > 0 && (
              <Section label="Interface (I/O schema)">
                <pre className="text-xs bg-gray-50 text-gray-800 p-3 rounded-lg overflow-x-auto">
                  {JSON.stringify(skill.interface, null, 2)}
                </pre>
              </Section>
            )}

            {/* Dependencies */}
            {((pipReqs && pipReqs.length > 0) || (sysReqs && sysReqs.length > 0)) && (
              <Section label="Dependencies">
                {pipReqs && pipReqs.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-1">
                    {pipReqs.map((pkg) => (
                      <span
                        key={pkg}
                        className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded"
                      >
                        {pkg}
                      </span>
                    ))}
                  </div>
                )}
                {sysReqs && sysReqs.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {sysReqs.map((pkg) => (
                      <span
                        key={pkg}
                        className="text-xs px-2 py-0.5 bg-orange-50 text-orange-700 rounded"
                      >
                        sys: {pkg}
                      </span>
                    ))}
                  </div>
                )}
              </Section>
            )}

            {/* Test Cases */}
            {skill.test_cases && skill.test_cases.length > 0 && (
              <Section label={`Test Cases (${skill.test_cases.length})`}>
                <div className="space-y-2">
                  {skill.test_cases.map((tc, i) => (
                    <div
                      key={i}
                      className="text-xs bg-gray-50 p-2 rounded-lg space-y-1"
                    >
                      <div className="font-medium text-gray-700">{tc.name}</div>
                      {tc.description && (
                        <div className="text-gray-500">{tc.description}</div>
                      )}
                      <div className="text-gray-500">
                        Input: {JSON.stringify(tc.input)}
                      </div>
                      <div className="text-gray-500">
                        Expected: {JSON.stringify(tc.expected_output)}
                      </div>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Footer metadata */}
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400 pt-3 border-t">
              <span>ID: {skill.id}</span>
              <span>Created: {new Date(skill.created_at).toLocaleString()}</span>
              {skill.version_count != null && (
                <span>Versions: {skill.version_count}</span>
              )}
              {skill.parent_id && (
                <span>Parent: {skill.parent_id.slice(0, 8)}</span>
              )}
              <span>
                Status: {skill.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
          </div>
        ) : null}

        <DialogFooter showCloseButton />
      </DialogContent>
    </Dialog>
  )
}

function Section({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
        {label}
      </h4>
      {children}
    </div>
  )
}
