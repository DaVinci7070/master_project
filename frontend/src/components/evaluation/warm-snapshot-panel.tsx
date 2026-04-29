'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { fetchSnapshots, saveWarmSnapshot, restoreWarmSnapshot } from '@/lib/api'
import type { SnapshotInfo } from '@/types'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function WarmSnapshotPanel() {
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([])
  const [snapshotName, setSnapshotName] = useState('')
  const [saving, setSaving] = useState(false)
  const [restoring, setRestoring] = useState<string | null>(null)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  async function loadSnapshots() {
    try {
      const data = await fetchSnapshots()
      setSnapshots(data)
    } catch {
      // Snapshots dir may not exist yet
      setSnapshots([])
    }
  }

  useEffect(() => {
    loadSnapshots()
  }, [])

  async function handleSave() {
    if (!snapshotName.trim()) return
    setSaving(true)
    setMessage(null)
    try {
      const name = snapshotName.endsWith('.dump') ? snapshotName : `${snapshotName}.dump`
      await saveWarmSnapshot(name)
      setMessage({ type: 'success', text: `Snapshot "${name}" saved` })
      setSnapshotName('')
      loadSnapshots()
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  async function handleRestore(filename: string) {
    setRestoring(filename)
    setMessage(null)
    try {
      const result = await restoreWarmSnapshot(filename)
      setMessage({
        type: result.returncode === 0 ? 'success' : 'error',
        text: result.returncode === 0
          ? `Restored from "${filename}"`
          : `Restore completed with warnings (exit code ${result.returncode})`,
      })
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : 'Restore failed' })
    } finally {
      setRestoring(null)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Warm Snapshots</CardTitle>
        <CardDescription>
          Save the current database state (pg_dump + Qdrant) and restore it later
          for warm-start evaluation.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Save form */}
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <Label htmlFor="snapshot-name">Snapshot Name</Label>
            <Input
              id="snapshot-name"
              placeholder="e.g. after_10_runs"
              value={snapshotName}
              onChange={(e) => setSnapshotName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSave()}
            />
          </div>
          <Button onClick={handleSave} disabled={saving || !snapshotName.trim()}>
            {saving ? 'Saving...' : 'Save Snapshot'}
          </Button>
        </div>

        {/* Snapshot list */}
        {snapshots.length > 0 ? (
          <div className="space-y-2">
            <p className="text-sm font-medium text-muted-foreground">
              Available Snapshots ({snapshots.length})
            </p>
            {snapshots.map((snap) => (
              <div
                key={snap.filename}
                className="flex items-center justify-between p-2 rounded border text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono">{snap.filename}</span>
                  <Badge variant="secondary">{formatBytes(snap.size_bytes)}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {new Date(snap.modified_at).toLocaleString()}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleRestore(snap.filename)}
                  disabled={restoring !== null}
                >
                  {restoring === snap.filename ? 'Restoring...' : 'Restore'}
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No snapshots yet.</p>
        )}

        {message && (
          <div className={`p-3 rounded-lg text-sm ${
            message.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
          }`}>
            {message.text}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
