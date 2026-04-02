'use client'

import { useState, useEffect } from 'react'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { fetchUserSettings, updateUserSettings } from '@/lib/api'
import { Zap, ZapOff } from 'lucide-react'

export function AutoApplyToggle() {
  const [autoApply, setAutoApply] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    loadSettings()
  }, [])

  async function loadSettings() {
    try {
      const settings = await fetchUserSettings()
      setAutoApply(settings.auto_apply)
    } catch (error) {
      console.error('Failed to load settings:', error)
    } finally {
      setIsLoading(false)
    }
  }

  async function handleToggle(checked: boolean) {
    setIsSaving(true)
    try {
      const updated = await updateUserSettings({ auto_apply: checked })
      setAutoApply(updated.auto_apply)
    } catch (error) {
      console.error('Failed to update settings:', error)
      // Revert on error
      setAutoApply(!checked)
    } finally {
      setIsSaving(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-100 animate-pulse">
        <div className="w-4 h-4 bg-gray-300 rounded" />
        <div className="w-20 h-4 bg-gray-300 rounded" />
      </div>
    )
  }

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-colors ${
      autoApply
        ? 'bg-yellow-100 border border-yellow-300'
        : 'bg-gray-100 border border-gray-200'
    }`}>
      {autoApply ? (
        <Zap className="w-4 h-4 text-yellow-600" />
      ) : (
        <ZapOff className="w-4 h-4 text-gray-400" />
      )}
      <Label htmlFor="auto-apply" className={`text-sm font-medium cursor-pointer ${
        autoApply ? 'text-yellow-700' : 'text-gray-600'
      }`}>
        Auto-Apply
      </Label>
      <Switch
        id="auto-apply"
        checked={autoApply}
        onCheckedChange={handleToggle}
        disabled={isSaving}
        className={isSaving ? 'opacity-50' : ''}
      />
    </div>
  )
}
