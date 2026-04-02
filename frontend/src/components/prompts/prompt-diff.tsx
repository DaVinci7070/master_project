'use client'

import { useMemo } from 'react'
import { Diff, Hunk, parseDiff } from 'react-diff-view'
import 'react-diff-view/style/index.css'

interface PromptDiffProps {
  oldContent: string
  newContent: string
  oldVersion: number
  newVersion: number
}

// Simple diff generator for text content
function generateUnifiedDiff(oldText: string, newText: string, oldName: string, newName: string): string {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')

  // Simple line-by-line diff (basic implementation)
  const hunks: string[] = []
  hunks.push(`--- ${oldName}`)
  hunks.push(`+++ ${newName}`)

  // Generate a single hunk for simplicity
  hunks.push(`@@ -1,${oldLines.length} +1,${newLines.length} @@`)

  const maxLen = Math.max(oldLines.length, newLines.length)

  for (let i = 0; i < maxLen; i++) {
    const oldLine = oldLines[i]
    const newLine = newLines[i]

    if (oldLine === newLine) {
      if (oldLine !== undefined) {
        hunks.push(` ${oldLine}`)
      }
    } else {
      if (oldLine !== undefined) {
        hunks.push(`-${oldLine}`)
      }
      if (newLine !== undefined) {
        hunks.push(`+${newLine}`)
      }
    }
  }

  return hunks.join('\n')
}

export function PromptDiff({ oldContent, newContent, oldVersion, newVersion }: PromptDiffProps) {
  const diffText = useMemo(() => {
    return generateUnifiedDiff(
      oldContent,
      newContent,
      `v${oldVersion}`,
      `v${newVersion}`
    )
  }, [oldContent, newContent, oldVersion, newVersion])

  const files = useMemo(() => {
    try {
      return parseDiff(diffText)
    } catch (error) {
      console.error('Failed to parse diff:', error)
      return []
    }
  }, [diffText])

  if (files.length === 0) {
    // Fallback: show simple before/after
    return (
      <div className="grid grid-cols-2 gap-4">
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">v{oldVersion}</h4>
          <pre className="text-xs bg-red-50 p-3 rounded-lg whitespace-pre-wrap">{oldContent}</pre>
        </div>
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">v{newVersion}</h4>
          <pre className="text-xs bg-green-50 p-3 rounded-lg whitespace-pre-wrap">{newContent}</pre>
        </div>
      </div>
    )
  }

  return (
    <div className="diff-view-wrapper text-sm">
      {files.map((file, i) => (
        <Diff key={i} viewType="unified" diffType="modify" hunks={file.hunks}>
          {(hunks) => hunks.map((hunk) => <Hunk key={hunk.content} hunk={hunk} />)}
        </Diff>
      ))}
    </div>
  )
}
