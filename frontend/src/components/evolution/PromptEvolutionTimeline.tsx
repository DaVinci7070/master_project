'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { GitBranch, Sparkles } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { PromptDiff } from '@/components/prompts/prompt-diff'
import { useEvolutionEvents } from '@/hooks'
import { fetchAgents, fetchPrompt, fetchPrompts } from '@/lib/api'
import type { Agent, EvolutionEvent, Prompt } from '@/types'
import { cn } from '@/lib/utils'

interface VersionNode extends Prompt {
  /** 1-based index in the chronologically-sorted chain. */
  versionIndex: number
}

interface Chain {
  rootId: string
  versions: VersionNode[]
  /** Human-readable agent names currently pointing into this lineage. */
  agentLabels: string[]
  /** Count of evolution.prompt_updated events whose artifact_id lives in this chain. */
  evolutionCount: number
  /** Most recent activity in the chain (ISO date string, used for sorting). */
  latestAt: string
}

interface DiffState {
  open: boolean
  parentId: string | null
  childId: string
  parentVersion: number | null
  childVersion: number
}

// ---------------------------------------------------------------- helpers

function buildChains(prompts: Prompt[], agents: Agent[], events: EvolutionEvent[]): Chain[] {
  const byId = new Map<string, Prompt>(prompts.map((p) => [p.id, p]))

  function rootOf(id: string): string {
    let cur: Prompt | undefined = byId.get(id)
    if (!cur) return id
    const seen = new Set<string>([cur.id])
    while (cur.parent_id) {
      const parent = byId.get(cur.parent_id)
      if (!parent || seen.has(parent.id)) break
      seen.add(parent.id)
      cur = parent
    }
    return cur.id
  }

  // Bucket prompts by their root.
  const buckets = new Map<string, Prompt[]>()
  for (const p of prompts) {
    const root = rootOf(p.id)
    const arr = buckets.get(root) ?? []
    arr.push(p)
    buckets.set(root, arr)
  }

  // Map agents → root (via their current prompt_id).
  const agentsByRoot = new Map<string, Set<string>>()
  for (const a of agents) {
    if (!a.prompt_id) continue
    const root = rootOf(a.prompt_id)
    const set = agentsByRoot.get(root) ?? new Set<string>()
    set.add(a.name)
    agentsByRoot.set(root, set)
  }

  // Count prompt-update events per root. An event's data.artifact_id points at the
  // new prompt version — resolve to root for grouping.
  const evoByRoot = new Map<string, number>()
  for (const e of events) {
    if (e.event_type !== 'evolution.prompt_updated') continue
    const artifactId = (e.data as { artifact_id?: string })?.artifact_id
    if (!artifactId) continue
    if (!byId.has(artifactId)) continue
    const root = rootOf(artifactId)
    evoByRoot.set(root, (evoByRoot.get(root) ?? 0) + 1)
  }

  const chains: Chain[] = []
  for (const [rootId, bucket] of buckets.entries()) {
    bucket.sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    )
    const versions: VersionNode[] = bucket.map((p, i) => ({ ...p, versionIndex: i + 1 }))
    const labels = Array.from(agentsByRoot.get(rootId) ?? new Set<string>())
    const latestAt = versions.length > 0 ? versions[versions.length - 1].created_at : ''
    chains.push({
      rootId,
      versions,
      agentLabels: labels.sort((a, b) => a.localeCompare(b)),
      evolutionCount: evoByRoot.get(rootId) ?? 0,
      latestAt,
    })
  }

  // Most-evolved (most versions), then most-recent, then alpha.
  chains.sort((a, b) => {
    if (b.versions.length !== a.versions.length) return b.versions.length - a.versions.length
    if (a.latestAt && b.latestAt && a.latestAt !== b.latestAt) {
      return new Date(b.latestAt).getTime() - new Date(a.latestAt).getTime()
    }
    const an = a.versions[0]?.name ?? ''
    const bn = b.versions[0]?.name ?? ''
    return an.localeCompare(bn)
  })
  return chains
}

function formatRelative(iso: string): string {
  if (!iso) return ''
  const ts = new Date(iso).getTime()
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

// ---------------------------------------------------------------- diff modal

interface DiffModalProps {
  state: DiffState
  onClose: () => void
}

function DiffModal({ state, onClose }: DiffModalProps) {
  const [loading, setLoading] = useState(true)
  const [oldContent, setOldContent] = useState<string>('')
  const [newContent, setNewContent] = useState<string>('')
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!state.open) return
    let cancelled = false

    async function load() {
      setLoading(true)
      setErr(null)
      try {
        const [child, parent] = await Promise.all([
          fetchPrompt(state.childId),
          state.parentId ? fetchPrompt(state.parentId) : Promise.resolve(null),
        ])
        if (cancelled) return
        setNewContent(child.content ?? '')
        setOldContent(parent?.content ?? '')
      } catch (e) {
        if (cancelled) return
        setErr(e instanceof Error ? e.message : 'Failed to load prompt content')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [state.childId, state.parentId, state.open])

  const hasParent = state.parentId !== null && state.parentVersion !== null

  return (
    <Dialog open={state.open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-5xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {hasParent
              ? `Prompt diff: v${state.parentVersion} → v${state.childVersion}`
              : `Prompt root version v${state.childVersion}`}
          </DialogTitle>
          <DialogDescription>
            {hasParent
              ? 'Line-by-line diff against the parent version.'
              : 'This is the root of the lineage — no parent to compare against.'}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-40" />
          </div>
        ) : err ? (
          <p className="text-sm text-destructive">{err}</p>
        ) : hasParent ? (
          <div className="rounded-lg border p-3">
            <PromptDiff
              oldContent={oldContent}
              newContent={newContent}
              oldVersion={state.parentVersion ?? 0}
              newVersion={state.childVersion}
            />
          </div>
        ) : (
          <pre className="text-xs whitespace-pre-wrap rounded-lg bg-muted p-3">
            {newContent || '(empty content)'}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------- chain row

function ChainRow({
  chain,
  onSelect,
}: {
  chain: Chain
  onSelect: (v: VersionNode, parent: VersionNode | null) => void
}) {
  const labelText =
    chain.agentLabels.length === 0
      ? chain.versions[0]?.name ?? 'unknown'
      : chain.agentLabels.join(', ')

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base truncate">
              <GitBranch className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{labelText}</span>
            </CardTitle>
            <CardDescription className="truncate">
              {chain.versions[0]?.name} · root {chain.rootId.slice(0, 8)}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Badge variant="secondary">
              {chain.versions.length} {chain.versions.length === 1 ? 'version' : 'versions'}
            </Badge>
            {chain.evolutionCount > 0 && (
              <Badge variant="default" className="gap-1">
                <Sparkles className="h-3 w-3" />
                {chain.evolutionCount} evolved
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <div className="flex items-center gap-0 min-w-fit py-4 pr-4">
            {chain.versions.map((v, i) => {
              const prev = i > 0 ? chain.versions[i - 1] : null
              const isRoot = i === 0
              const isLatest = i === chain.versions.length - 1
              return (
                <div key={v.id} className="flex items-center">
                  {i > 0 && (
                    <div className="h-px w-10 shrink-0 bg-border" aria-hidden="true" />
                  )}
                  <button
                    type="button"
                    onClick={() => onSelect(v, prev)}
                    title={`${v.name} · v${v.versionIndex} · ${new Date(
                      v.created_at
                    ).toLocaleString()}`}
                    className={cn(
                      'group flex flex-col items-center gap-1.5 focus:outline-none',
                      'focus-visible:ring-2 focus-visible:ring-ring rounded-md'
                    )}
                  >
                    <span
                      className={cn(
                        'relative grid h-9 w-9 place-items-center rounded-full border-2 text-xs font-semibold transition-all',
                        isLatest
                          ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                          : isRoot
                            ? 'border-muted-foreground/40 bg-background text-muted-foreground group-hover:border-primary/60'
                            : 'border-primary/40 bg-background text-primary group-hover:border-primary group-hover:bg-primary/5'
                      )}
                    >
                      v{v.versionIndex}
                      {v.is_active && (
                        <span
                          className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-emerald-500 ring-2 ring-background"
                          title="Currently active"
                        />
                      )}
                    </span>
                    <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                      {formatRelative(v.created_at)}
                    </span>
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------- main

export function PromptEvolutionTimeline() {
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [diff, setDiff] = useState<DiffState>({
    open: false,
    parentId: null,
    childId: '',
    parentVersion: null,
    childVersion: 0,
  })

  const { events } = useEvolutionEvents({ limit: 500 })

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [p, a] = await Promise.all([fetchPrompts(), fetchAgents()])
        if (cancelled) return
        setPrompts(p)
        setAgents(a)
      } catch (e) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Failed to load prompt lineage')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  // Refresh prompt list when a new prompt version is reported in the event stream.
  const promptUpdateCount = useMemo(
    () => events.filter((e) => e.event_type === 'evolution.prompt_updated').length,
    [events]
  )
  const lastSeenCountRef = useRef(0)
  useEffect(() => {
    // Skip the initial mount (count = 0 seen once); only react to real changes.
    if (promptUpdateCount === lastSeenCountRef.current) return
    lastSeenCountRef.current = promptUpdateCount
    let cancelled = false
    fetchPrompts()
      .then((p) => {
        if (!cancelled) setPrompts(p)
      })
      .catch(() => {
        /* keep existing state on transient failures */
      })
    return () => {
      cancelled = true
    }
  }, [promptUpdateCount])

  const chains = useMemo(() => buildChains(prompts, agents, events), [prompts, agents, events])

  const evolvedCount = chains.filter((c) => c.versions.length > 1).length
  const totalVersions = chains.reduce((acc, c) => acc + c.versions.length, 0)

  const handleSelect = (v: VersionNode, parent: VersionNode | null) => {
    setDiff({
      open: true,
      parentId: parent?.id ?? null,
      childId: v.id,
      parentVersion: parent?.versionIndex ?? null,
      childVersion: v.versionIndex,
    })
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-20" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
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

  if (chains.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">No prompt versions yet</CardTitle>
          <CardDescription>
            Run an execution — the evolution loop creates new prompt versions when the
            analysis pipeline surfaces improvement findings.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
        <span>
          <span className="font-medium text-foreground">{chains.length}</span> lineages
        </span>
        <span>
          <span className="font-medium text-foreground">{totalVersions}</span> total versions
        </span>
        <span>
          <span className="font-medium text-foreground">{evolvedCount}</span> with multiple versions
        </span>
      </div>

      <div className="space-y-3">
        {chains.map((chain) => (
          <ChainRow key={chain.rootId} chain={chain} onSelect={handleSelect} />
        ))}
      </div>

      <DiffModal state={diff} onClose={() => setDiff((s) => ({ ...s, open: false }))} />
    </div>
  )
}