'use client'

import { useEffect, useState, useMemo } from 'react'
import { SkillCard } from './skill-card'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchSkills } from '@/lib/api'
import type { Skill } from '@/types'

type HealthFilter = 'all' | 'healthy' | 'warning' | 'inactive'

export function SkillList() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [healthFilter, setHealthFilter] = useState<HealthFilter>('all')

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchSkills()
        setSkills(data)
      } catch (error) {
        console.error('Failed to fetch skills:', error)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const getHealthStatus = (skill: Skill) => {
    if (!skill.is_active) return 'inactive'
    // Use test_count from summary response, fallback to test_cases length
    const testCount = skill.test_count ?? skill.test_cases?.length ?? 0
    if (testCount >= 3) return 'healthy'
    if (testCount > 0) return 'warning'
    return 'unknown'
  }

  const filteredSkills = useMemo(() => {
    return skills.filter((skill) => {
      // Search filter
      const searchMatch =
        search === '' ||
        skill.name.toLowerCase().includes(search.toLowerCase()) ||
        skill.description?.toLowerCase().includes(search.toLowerCase())

      // Health filter
      const healthStatus = getHealthStatus(skill)
      const healthMatch =
        healthFilter === 'all' ||
        (healthFilter === 'healthy' && healthStatus === 'healthy') ||
        (healthFilter === 'warning' &&
          (healthStatus === 'warning' || healthStatus === 'unknown')) ||
        (healthFilter === 'inactive' && healthStatus === 'inactive')

      return searchMatch && healthMatch
    })
  }, [skills, search, healthFilter])

  const stats = useMemo(() => {
    const healthy = skills.filter(
      (s) => getHealthStatus(s) === 'healthy'
    ).length
    const warning = skills.filter((s) =>
      ['warning', 'unknown'].includes(getHealthStatus(s))
    ).length
    const inactive = skills.filter((s) => !s.is_active).length
    return { total: skills.length, healthy, warning, inactive }
  }, [skills])

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex gap-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-10 w-32" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} className="h-48" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="flex items-center gap-4 text-sm text-gray-500">
        <span>{stats.total} total</span>
        <span className="text-green-600">{stats.healthy} healthy</span>
        <span className="text-yellow-600">{stats.warning} need tests</span>
        <span className="text-gray-400">{stats.inactive} inactive</span>
      </div>

      {/* Search and Filter */}
      <div className="flex flex-col sm:flex-row gap-4">
        <input
          type="text"
          placeholder="Search skills..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
        <select
          value={healthFilter}
          onChange={(e) => setHealthFilter(e.target.value as HealthFilter)}
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        >
          <option value="all">All Status</option>
          <option value="healthy">Healthy Only</option>
          <option value="warning">Needs Tests</option>
          <option value="inactive">Inactive</option>
        </select>
      </div>

      {/* Skill Grid */}
      {filteredSkills.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          {skills.length === 0
            ? 'No skills found'
            : 'No skills match your search'}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredSkills.map((skill) => (
            <SkillCard key={skill.id} skill={skill} />
          ))}
        </div>
      )}
    </div>
  )
}
