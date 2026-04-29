'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronRight,
  GitCommit,
  History,
  MinusCircle,
  PlusCircle,
  RefreshCw,
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
import { Skeleton } from '@/components/ui/skeleton'
import { useEvolutionEvents } from '@/hooks'
import { fetchTopologyHistory } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { TopologyHistoryEntry } from '@/types'

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

function dayKey(iso: string): string {
  if (!iso) return 'unknown'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'unknown'
  // YYYY-MM-DD — stable sort key + human-friendly display below.
  return d.toISOString().slice(0, 10)
}

function dayLabel(key: string): string {
  if (key === 'unknown') return 'Unknown date'
  const today = new Date().toISOString().slice(0, 10)
  const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)
  if (key === today) return 'Today'
  if (key === yesterday) return 'Yesterday'
  // Fall back to a readable long-form label.
  try {
    return new Date(key).toLocaleDateString(undefined, {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return key
  }
}

const CHANGE_ICON_CLASS = 'h-4 w-4 shrink-0'

function ChangeIcon({ changeType }: { changeType: string }) {
  const t = changeType.toLowerCase()
  if (t.includes('add') || t.includes('create'))
    return <PlusCircle className={cn(CHANGE_ICON_CLASS, 'text-emerald-500')} />
  if (t.includes('remove') || t.includes('delete'))
    return <MinusCircle className={cn(CHANGE_ICON_CLASS, 'text-destructive')} />
  if (t.includes('update') || t.includes('change') || t.includes('modify'))
    return <RefreshCw className={cn(CHANGE_ICON_CLASS, 'text-sky-500')} />
  return <GitCommit className={cn(CHANGE_ICON_CLASS, 'text-muted-foreground')} />
}

function SourceBadge({ source }: { source: string | null | undefined }) {
  if (!source) return null
  const label = source.replace(/_/g, ' ')
  const tone: Record<string, string> = {
    self_healing: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    evolution:
      'border-indigo-500/40 bg-indigo-500/10 text-indigo-700 dark:text-indigo-300',
    manual:
      'border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300',
    migration:
      'border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300',
    system:
      'border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300',
  }
  const className = tone[source] ?? tone.system
  return (
    <Badge variant="outline" className={cn('text-[10px] capitalize', className)}>
      {label}
    </Badge>
  )
}

// ---------------------------------------------------------------- JSON diff

type DiffStatus = 'added' | 'removed' | 'modified' | 'unchanged'

interface DiffRow {
  key: string
  status: DiffStatus
  previous: unknown
  next: unknown
}

function stableStringify(value: unknown): string {
  // Stable, compact JSON for deep-equality comparison.
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  const obj = value as Record<string, unknown>
  const keys = Object.keys(obj).sort()
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(',')}}`
}

function computeDiff(
  previous: Record<string, unknown> | null,
  next: Record<string, unknown> | null
): DiffRow[] {
  const prev = previous ?? {}
  const curr = next ?? {}
  const keys = Array.from(new Set([...Object.keys(prev), ...Object.keys(curr)])).sort()
  const rows: DiffRow[] = []
  for (const key of keys) {
    const hasPrev = key in prev
    const hasCurr = key in curr
    if (hasPrev && !hasCurr) {
      rows.push({ key, status: 'removed', previous: prev[key], next: undefined })
    } else if (!hasPrev && hasCurr) {
      rows.push({ key, status: 'added', previous: undefined, next: curr[key] })
    } else {
      const same = stableStringify(prev[key]) === stableStringify(curr[key])
      rows.push({
        key,
        status: same ? 'unchanged' : 'modified',
        previous: prev[key],
        next: curr[key],
      })
    }
  }
  return rows
}

function renderValue(value: unknown): string {
  if (value === undefined) return '—'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function StateColumn({
  title,
  state,
  highlight,
  emptyLabel,
}: {
  title: string
  state: Record<string, unknown> | null
  highlight: 'previous' | 'next'
  emptyLabel: string
}) {
  const rows = useMemo(() => {
    if (!state) return [] as DiffRow[]
    // For the column view we still want a stable ordering.
    return Object.keys(state)
      .sort()
      .map((key) => ({
        key,
        status: 'unchanged' as DiffStatus,
        previous: state[key],
        next: state[key],
      }))
  }, [state])

  return (
    <div className="rounded-md border bg-muted/30">
      <div className="border-b bg-background/60 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="p-3">
        {!state ? (
          <p className="text-[11px] italic text-muted-foreground">{emptyLabel}</p>
        ) : rows.length === 0 ? (
          <p className="text-[11px] italic text-muted-foreground">(empty object)</p>
        ) : (
          <dl className="space-y-1 text-[11px]">
            {rows.map((row) => (
              <div
                key={row.key}
                className={cn(
                  'rounded px-2 py-1 break-words',
                  highlight === 'previous'
                    ? 'bg-rose-500/5'
                    : 'bg-emerald-500/5'
                )}
              >
                <dt className="font-mono font-medium text-muted-foreground">{row.key}</dt>
                <dd>
                  <pre className="whitespace-pre-wrap font-mono text-foreground">
                    {renderValue(highlight === 'previous' ? row.previous : row.next)}
                  </pre>
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  )
}

function DiffTable({
  previous,
  next,
}: {
  previous: Record<string, unknown> | null
  next: Record<string, unknown> | null
}) {
  const rows = useMemo(() => computeDiff(previous, next), [previous, next])
  const interesting = rows.filter((r) => r.status !== 'unchanged')

  if (interesting.length === 0) {
    return (
      <p className="text-[11px] italic text-muted-foreground">
        No field-level differences detected.
      </p>
    )
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <div className="grid grid-cols-[10rem_1fr_1fr] gap-px bg-border text-[11px]">
        <div className="bg-background px-3 py-1.5 font-medium text-muted-foreground">
          Field
        </div>
        <div className="bg-background px-3 py-1.5 font-medium text-muted-foreground">
          Before
        </div>
        <div className="bg-background px-3 py-1.5 font-medium text-muted-foreground">
          After
        </div>
        {interesting.map((row) => (
          <DiffCellRow key={row.key} row={row} />
        ))}
      </div>
    </div>
  )
}

function DiffCellRow({ row }: { row: DiffRow }) {
  const tone: Record<DiffStatus, string> = {
    added: 'bg-emerald-500/10 text-emerald-900 dark:text-emerald-200',
    removed: 'bg-rose-500/10 text-rose-900 dark:text-rose-200',
    modified: 'bg-amber-500/10 text-amber-900 dark:text-amber-200',
    unchanged: 'bg-background',
  }
  return (
    <>
      <div className={cn('px-3 py-2 font-mono text-[11px] break-words', tone[row.status])}>
        <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">
          {row.status}
        </span>
        {row.key}
      </div>
      <div className={cn('px-3 py-2 break-words', tone[row.status])}>
        <pre className="whitespace-pre-wrap font-mono text-[11px]">
          {renderValue(row.previous)}
        </pre>
      </div>
      <div className={cn('px-3 py-2 break-words', tone[row.status])}>
        <pre className="whitespace-pre-wrap font-mono text-[11px]">
          {renderValue(row.next)}
        </pre>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- change row

function ChangeRow({ entry }: { entry: TopologyHistoryEntry }) {
  const [open, setOpen] = useState(false)
  const hasStates = !!(entry.previous_state || entry.new_state)
  const hasDetails = !!(
    entry.change_details && Object.keys(entry.change_details).length > 0
  )
  const expandable = hasStates || hasDetails

  return (
    <div className="rounded-lg border bg-card">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            disabled={!expandable}
            className={cn(
              'group flex w-full items-center gap-3 px-3 py-2 text-left',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              expandable
                ? 'hover:bg-accent/40 cursor-pointer'
                : 'cursor-default opacity-90'
            )}
          >
            <ChangeIcon changeType={entry.change_type} />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="text-[10px] capitalize">
                  {entry.change_type.replace(/_/g, ' ')}
                </Badge>
                {entry.entity_name && (
                  <span className="text-sm font-medium truncate">
                    {entry.entity_name}
                  </span>
                )}
                {entry.entity_type && (
                  <Badge variant="secondary" className="text-[10px] capitalize">
                    {entry.entity_type}
                  </Badge>
                )}
                <SourceBadge source={entry.source} />
              </div>
              {(entry.triggered_by || entry.description) && (
                <p className="text-[11px] text-muted-foreground truncate">
                  {entry.triggered_by && (
                    <span className="mr-2">by {entry.triggered_by}</span>
                  )}
                  {entry.description && <span>{entry.description}</span>}
                </p>
              )}
            </div>
            <span className="text-[11px] text-muted-foreground whitespace-nowrap">
              {formatRelative(entry.timestamp)}
            </span>
            {expandable && (
              <ChevronRight
                className={cn(
                  'h-4 w-4 shrink-0 text-muted-foreground transition-transform',
                  open && 'rotate-90'
                )}
              />
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="border-t space-y-4 p-3">
            {hasStates && (
              <div className="space-y-2">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  State
                </p>
                <div className="grid gap-3 md:grid-cols-2">
                  <StateColumn
                    title="Previous"
                    state={entry.previous_state}
                    highlight="previous"
                    emptyLabel="(no previous state)"
                  />
                  <StateColumn
                    title="New"
                    state={entry.new_state}
                    highlight="next"
                    emptyLabel="(no new state)"
                  />
                </div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground pt-2">
                  Field-level diff
                </p>
                <DiffTable
                  previous={entry.previous_state}
                  next={entry.new_state}
                />
              </div>
            )}
            {hasDetails && (
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
                  Details
                </p>
                <pre className="overflow-x-auto rounded bg-muted p-2 text-[11px] whitespace-pre-wrap">
                  {JSON.stringify(entry.change_details, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

// ---------------------------------------------------------------- main

export function TopologyChangeHistory() {
  const [entries, setEntries] = useState<TopologyHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { events } = useEvolutionEvents({ limit: 200 })
  const topologyEventCount = useMemo(
    () => events.filter((e) => e.event_type === 'evolution.topology_changed').length,
    [events]
  )
  const lastSeenCountRef = useRef(0)

  const load = async () => {
    try {
      const data = await fetchTopologyHistory(50)
      setEntries(data.entries)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load topology history')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchTopologyHistory(50)
      .then((data) => {
        if (cancelled) return
        setEntries(data.entries)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Failed to load topology history')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Refresh when telemetry reports a new topology change (skip the "0 -> 0" mount).
  useEffect(() => {
    if (topologyEventCount === lastSeenCountRef.current) return
    lastSeenCountRef.current = topologyEventCount
    void load()
  }, [topologyEventCount])

  const sorted = useMemo(
    () =>
      [...entries].sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      ),
    [entries]
  )

  const grouped = useMemo(() => {
    const groups = new Map<string, TopologyHistoryEntry[]>()
    for (const entry of sorted) {
      const key = dayKey(entry.timestamp)
      const arr = groups.get(key) ?? []
      arr.push(entry)
      groups.set(key, arr)
    }
    return Array.from(groups.entries())
  }, [sorted])

  const byType = useMemo(() => {
    const counts = new Map<string, number>()
    for (const entry of sorted) {
      counts.set(entry.change_type, (counts.get(entry.change_type) ?? 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [sorted])

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-12" />
        <Skeleton className="h-24" />
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

  if (sorted.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">No topology changes yet</CardTitle>
          <CardDescription>
            Self-healing and evolution runs append entries here — expect the first one
            after the next execution that mutates the topology.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <History className="h-4 w-4 text-muted-foreground" />
            {sorted.length} changes
          </CardTitle>
          <CardDescription>
            Chronological archive of every topology adaptation.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {byType.map(([type, count]) => (
              <Badge key={type} variant="outline" className="text-[11px] capitalize">
                {type.replace(/_/g, ' ')} · {count}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-5">
        {grouped.map(([day, dayEntries]) => (
          <div key={day} className="space-y-2">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
              <span className="h-px flex-1 bg-border" aria-hidden="true" />
              <span>{dayLabel(day)}</span>
              <span className="h-px flex-1 bg-border" aria-hidden="true" />
            </div>
            <div className="space-y-2">
              {dayEntries.map((entry) => (
                <ChangeRow key={entry.id} entry={entry} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
