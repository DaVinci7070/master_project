import { SkillList } from '@/components/skills'

export default function SkillsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Skills</h1>
        <p className="text-gray-500 mt-1">
          All skills with health status and test coverage
        </p>
      </div>

      <SkillList />
    </div>
  )
}
