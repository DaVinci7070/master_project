import { PromptList } from '@/components/prompts'

export default function PromptsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Prompt Evolution</h1>
        <p className="text-gray-500 mt-1">Track prompt versions, diffs, and performance over time</p>
      </div>

      <PromptList />
    </div>
  )
}
