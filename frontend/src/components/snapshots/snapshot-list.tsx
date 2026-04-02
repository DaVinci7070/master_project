'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchExecutionSnapshots, createExecutionSnapshot } from '@/lib/api'

interface Snapshot {
  id: string
  created_at: string
  description: string
}

export function SnapshotList() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newDescription, setNewDescription] = useState('')

  async function load() {
    try {
      const data = await fetchExecutionSnapshots()
      setSnapshots(data)
    } catch (error) {
      console.error('Failed to fetch snapshots:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function handleCreate() {
    if (!newDescription.trim()) return
    setCreating(true)
    try {
      await createExecutionSnapshot(newDescription.trim())
      setNewDescription('')
      await load()
    } catch (error) {
      console.error('Failed to create snapshot:', error)
    } finally {
      setCreating(false)
    }
  }

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Execution Snapshots</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Execution Snapshots</CardTitle>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm">Create Snapshot</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create Execution Snapshot</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <p className="text-sm text-gray-500">
                  Capture the current system state for reproducibility.
                  This includes all agent configurations, active prompts, and skills.
                </p>
                <input
                  type="text"
                  placeholder="Snapshot description..."
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <Button
                  onClick={handleCreate}
                  disabled={creating || !newDescription.trim()}
                  className="w-full"
                >
                  {creating ? 'Creating...' : 'Create Snapshot'}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent>
        {snapshots.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-4">
            No snapshots yet. Create one to capture the current system state.
          </p>
        ) : (
          <div className="space-y-2">
            {snapshots.map((snapshot) => (
              <div
                key={snapshot.id}
                className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
              >
                <div>
                  <p className="font-medium text-sm">{snapshot.description}</p>
                  <p className="text-xs text-gray-500">
                    {new Date(snapshot.created_at).toLocaleString()}
                  </p>
                </div>
                <span className="text-xs font-mono text-gray-400">
                  {snapshot.id.slice(0, 8)}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
