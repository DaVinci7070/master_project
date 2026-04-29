'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckCircle2,
  ChevronRight,
  FileCode,
  GitBranch,
  Sparkles,
  XCircle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { PromptDiff } from '@/components/prompts/prompt-diff'
import { useEvolutionEvents } from '@/hooks'
import { fetchSkillVersionHistory, fetchSkills } from '@/lib/api'
import { cn } from '@/lib/utils'
import type {
  Skill,
  SkillBuildAttemptSummary,
  SkillVersionEntry,
  SkillVersionHistory,
} from '@/types'

// ---------------------------------------------------------------- helpers

function formatRelative(iso: string): string {
  if (!iso) return ''
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return ''
  const diffMs = Date.now() - ts
  const sec = Math.round(diffMs / 1000)
  if (sec < 60) return `${sec}s ago`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.round(hr / 24)
  return `${day}d ago`
}

/**
 * Pick the best code-snapshot for a version: prefer the latest successful
 * build-attempt; fall back to the latest attempt that actually has a snapshot.
 */
function snapshotForVersion(version: SkillVersionEntry): string | null {
  if (!version.build_attempts || version.build_attempts.length === 0) return null
  const sorted = [...version.build_attempts].sort(
    (a, b) => b.attempt_number - a.attempt_number
  )
  const successful = sorted.find((a) => a.success && a.code_snapshot)
  if (successful?.code_snapshot) return successful.code_snapshot
  const anyWithCode = sorted.find((a) => a.code_snapshot)
  return anyWithCode?.code_snapshot ?? null
}

// ---------------------------------------------------------------- build-attempt row

function BuildAttemptRow({ attempt }: { attempt: SkillBuildAttemptSummary }) {
  return (
    <div className="rounded-md border bg-muted/30 p-3 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          {attempt.success ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0 text-destructive" />
          )}
          <span className="text-sm font-medium">Attempt {attempt.attempt_number}</span>
          {attempt.error_type_classified && (
            <Badge variant="outline" className="text-[10px]">
              {attempt.error_type_classified}
            </Badge>
          )}
        </div>
        <span className="text-[11px] text-muted-foreground whitespace-nowrap">
          {formatRelative(attempt.created_at)}
        </span>
      </div>

      {attempt.approach && (
        <p className="text-xs text-muted-foreground line-clamp-2">
          <span className="font-medium text-foreground">Approach: </span>
          {attempt.approach}
        </p>
      )}

      {attempt.lesson_learned && (
        <blockquote className="border-l-4 border-primary/60 bg-background/60 pl-3 py-1 text-xs italic text-muted-foreground">
          {attempt.lesson_learned}
        </blockquote>
      )}

      {attempt.failure_analysis && Object.keys(attempt.failure_analysis).length > 0 && (
        <Collapsible>
          <CollapsibleTrigger
            className={cn(
              'group flex items-center gap-1 text-[11px] text-muted-foreground',
              'hover:text-foreground focus:outline-none focus-visible:underline'
            )}
          >
            <ChevronRight className="h-3 w-3 transition-transform group-data-[state=open]:rotate-90" />
            Failure analysis
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2">
            <pre className="overflow-x-auto rounded bg-muted p-2 text-[11px] whitespace-pre-wrap">
              {JSON.stringify(attempt.failure_analysis, null, 2)}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- version block

interface VersionBlockProps {
  version: SkillVersionEntry
  previous: SkillVersionEntry | null
  onShowDiff: (prev: SkillVersionEntry, curr: SkillVersionEntry) => void
}

function VersionBlock({ version, previous, onShowDiff }: VersionBlockProps) {
  const currentSnapshot = snapshotForVersion(version)
  const previousSnapshot = previous ? snapshotForVersion(previous) : null
  const canDiff = !!(previous && currentSnapshot && previousSnapshot)

  return (
    <div className="relative pl-6 pb-6 last:pb-0">
      {/* Timeline rail */}
      <span
        className="absolute left-[7px] top-2 bottom-0 w-px bg-border"
        aria-hidden="true"
      />
      <span
        className={cn(
          'absolute left-0 top-1.5 grid h-4 w-4 place-items-center rounded-full border-2',
          version.is_active
            ? 'border-primary bg-primary'
            : 'border-muted-foreground/40 bg-background'
        )}
        aria-hidden="true"
      />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">v{version.version_index}</Badge>
          {version.is_active && (
            <Badge variant="default" className="gap-1">
              <Sparkles className="h-3 w-3" />
              active
            </Badge>
          )}
          <span className="text-sm font-medium truncate">{version.name}</span>
          <span className="text-[11px] text-muted-foreground">
            {formatRelative(version.created_at)}
          </span>
          {canDiff && (
            <button
              type="button"
              onClick={() => onShowDiff(previous!, version)}
              className={cn(
                'ml-auto inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]',
                'hover:bg-accent hover:text-accent-foreground',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring'
              )}
              title={`Diff v${previous!.version_index} → v${version.version_index}`}
            >
              <FileCode className="h-3 w-3" />
              Show code diff
            </button>
          )}
        </div>

        {version.description && (
          <p className="text-xs text-muted-foreground">{version.description}</p>
        )}

        {version.build_attempts && version.build_attempts.length > 0 ? (
          <div className="space-y-2 pt-1">
            {version.build_attempts.map((a) => (
              <BuildAttemptRow key={a.id} attempt={a} />
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-muted-foreground italic">
            No build-attempt data recorded for this version.
          </p>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- diff modal

interface DiffState {
  open: boolean
  previous: SkillVersionEntry | null
  current: SkillVersionEntry | null
}

function CodeDiffModal({
  state,
  onClose,
}: {
  state: DiffState
  onClose: () => void
}) {
  const previousSnapshot = state.previous ? snapshotForVersion(state.previous) : null
  const currentSnapshot = state.current ? snapshotForVersion(state.current) : null

  return (
    <Dialog open={state.open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-5xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {state.previous && state.current
              ? `Skill code diff: v${state.previous.version_index} → v${state.current.version_index}`
              : 'Skill code diff'}
          </DialogTitle>
          <DialogDescription>
            Latest successful build-attempt snapshot of each version.
          </DialogDescription>
        </DialogHeader>
        {state.previous && state.current && previousSnapshot && currentSnapshot ? (
          <div className="rounded-lg border p-3">
            <PromptDiff
              oldContent={previousSnapshot}
              newContent={currentSnapshot}
              oldVersion={state.previous.version_index}
              newVersion={state.current.version_index}
            />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Snapshot unavailable for one of the versions.
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------- skill list item

interface SkillListItemProps {
  skill: Skill
  selected: boolean
  onSelect: (id: string) => void
}

function SkillListItem({ skill, selected, onSelect }: SkillListItemProps) {
  const versionCount = skill.version_count ?? 1
  const hasEvolved = versionCount > 1

  return (
    <button
      type="button"
      onClick={() => onSelect(skill.id)}
      className={cn(
        'w-full rounded-lg border px-3 py-2 text-left transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        selected
          ? 'border-primary bg-primary/5'
          : 'hover:border-primary/40 hover:bg-accent/40'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <GitBranch
            className={cn(
              'h-4 w-4 shrink-0 mt-0.5',
              hasEvolved ? 'text-primary' : 'text-muted-foreground'
            )}
          />
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{skill.name}</p>
            {skill.description && (
              <p className="text-[11px] text-muted-foreground line-clamp-2">
                {skill.description}
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <Badge variant={hasEvolved ? 'default' : 'secondary'} className="gap-1">
            {hasEvolved && <Sparkles className="h-3 w-3" />}v{versionCount}
          </Badge>
          {!skill.is_active && (
            <Badge variant="outline" className="text-[10px]">
              inactive
            </Badge>
          )}
        </div>
      </div>
    </button>
  )
}

// ---------------------------------------------------------------- detail panel

function SkillDetailPanel({ skillId }: { skillId: string | null }) {
  const [history, setHistory] = useState<SkillVersionHistory | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [diff, setDiff] = useState<DiffState>({
    open: false,
    previous: null,
    current: null,
  })
  const { events } = useEvolutionEvents({ limit: 200 })

  // Track skill_rebuilt events so we can refresh the currently-shown lineage.
  const rebuildCount = useMemo(
    () => events.filter((e) => e.event_type === 'evolution.skill_rebuilt').length,
    [events]
  )
  const lastSeenCountRef = useRef(0)

  useEffect(() => {
    if (!skillId) {
      setHistory(null)
      setError(null)
      return
    }
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await fetchSkillVersionHistory(skillId!)
        if (cancelled) return
        setHistory(data)
      } catch (e) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Failed to load version history')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [skillId])

  // Refresh on skill_rebuilt telemetry (skip the initial "0 -> 0" mount).
  useEffect(() => {
    if (!skillId) return
    if (rebuildCount === lastSeenCountRef.current) return
    lastSeenCountRef.current = rebuildCount
    let cancelled = false
    fetchSkillVersionHistory(skillId)
      .then((data) => {
        if (!cancelled) setHistory(data)
      })
      .catch(() => {
        /* keep existing data on transient failure */
      })
    return () => {
      cancelled = true
    }
  }, [rebuildCount, skillId])

  if (!skillId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Select a skill</CardTitle>
          <CardDescription>
            Pick a skill from the list to inspect its version lineage, build attempts
            and code diffs.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    )
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base text-destructive">Failed to load</CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (!history || history.lineage.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">No version data</CardTitle>
          <CardDescription>
            This skill has no lineage recorded yet. Only the root version exists.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  const lineage = history.lineage
  const latest = lineage[lineage.length - 1]
  const evolved = lineage.length > 1

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base truncate">
              <GitBranch className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{latest.name}</span>
            </CardTitle>
            <CardDescription>
              {history.total_versions} {history.total_versions === 1 ? 'version' : 'versions'}{' '}
              · root {history.skill_id.slice(0, 8)}
            </CardDescription>
          </div>
          {evolved && (
            <Badge variant="default" className="gap-1 shrink-0">
              <Sparkles className="h-3 w-3" />
              evolved
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div>
          {lineage.map((v, i) => (
            <VersionBlock
              key={v.id}
              version={v}
              previous={i > 0 ? lineage[i - 1] : null}
              onShowDiff={(prev, curr) =>
                setDiff({ open: true, previous: prev, current: curr })
              }
            />
          ))}
        </div>
      </CardContent>
      <CodeDiffModal
        state={diff}
        onClose={() => setDiff((s) => ({ ...s, open: false }))}
      />
    </Card>
  )
}

// ---------------------------------------------------------------- main

export function SkillEvolutionView() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { events } = useEvolutionEvents({ limit: 200 })
  const rebuildCount = useMemo(
    () => events.filter((e) => e.event_type === 'evolution.skill_rebuilt').length,
    [events]
  )
  const lastSeenCountRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await fetchSkills()
        if (cancelled) return
        setSkills(data)
      } catch (e) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Failed to load skills')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  // Refresh the skill list when a skill_rebuilt event comes in (new version_count).
  useEffect(() => {
    if (rebuildCount === lastSeenCountRef.current) return
    lastSeenCountRef.current = rebuildCount
    let cancelled = false
    fetchSkills()
      .then((data) => {
        if (!cancelled) setSkills(data)
      })
      .catch(() => {
        /* keep existing data on transient failure */
      })
    return () => {
      cancelled = true
    }
  }, [rebuildCount])

  const sorted = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = skills.filter((s) => {
      if (!q) return true
      const name = s.name.toLowerCase()
      const desc = (s.description ?? '').toLowerCase()
      return name.includes(q) || desc.includes(q)
    })
    return filtered.sort((a, b) => {
      const aEvolved = (a.version_count ?? 1) > 1
      const bEvolved = (b.version_count ?? 1) > 1
      if (aEvolved !== bEvolved) return aEvolved ? -1 : 1
      const at = new Date(a.created_at).getTime()
      const bt = new Date(b.created_at).getTime()
      return bt - at
    })
  }, [skills, search])

  // Auto-select the first skill once data is loaded (usually the most evolved one).
  useEffect(() => {
    if (selectedId) return
    if (sorted.length === 0) return
    setSelectedId(sorted[0].id)
  }, [selectedId, sorted])

  const evolvedCount = skills.filter((s) => (s.version_count ?? 1) > 1).length

  if (loading) {
    return (
      <div className="grid gap-4 lg:grid-cols-[minmax(260px,320px)_1fr]">
        <div className="space-y-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base text-destructive">Failed to load</CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (skills.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">No skills yet</CardTitle>
          <CardDescription>
            The evolution loop creates and rebuilds skills during executions — run one
            to populate this view.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
        <span>
          <span className="font-medium text-foreground">{skills.length}</span> skills
        </span>
        <span>
          <span className="font-medium text-foreground">{evolvedCount}</span> evolved
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(260px,320px)_1fr]">
        <div className="space-y-3">
          <input
            type="search"
            placeholder="Search skills…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={cn(
              'w-full rounded-md border bg-background px-3 py-2 text-sm',
              'placeholder:text-muted-foreground',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring'
            )}
          />
          <div className="space-y-2 max-h-[70vh] overflow-y-auto pr-1">
            {sorted.length === 0 ? (
              <p className="text-sm text-muted-foreground px-2 py-4">
                No skills match your search.
              </p>
            ) : (
              sorted.map((skill) => (
                <SkillListItem
                  key={skill.id}
                  skill={skill}
                  selected={skill.id === selectedId}
                  onSelect={setSelectedId}
                />
              ))
            )}
          </div>
        </div>

        <SkillDetailPanel skillId={selectedId} />
      </div>
    </div>
  )
}
