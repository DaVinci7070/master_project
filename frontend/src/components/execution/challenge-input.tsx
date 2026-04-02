'use client'

import { useState, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { submitChallenge, uploadChallengeFile } from '@/lib/api'
import type { ChallengeAnalysisResponse } from '@/types'

interface ChallengeInputProps {
  onSubmit: (response: ChallengeAnalysisResponse) => void
  onError: (error: Error) => void
  disabled?: boolean
}

const MAX_CHARACTERS = 10000
const MAX_FILE_SIZE = 50 * 1024 * 1024

const FILE_CATEGORIES: Record<string, string[]> = {
  document: ['.pdf', '.doc', '.docx', '.odt', '.rtf'],
  spreadsheet: ['.xlsx', '.xls', '.csv', '.ods'],
  text: ['.txt', '.md', '.json', '.xml', '.yaml', '.yml'],
  audio: ['.mp3', '.wav', '.m4a', '.ogg', '.opus', '.flac', '.aac'],
  video: ['.mp4', '.mov', '.avi', '.mkv', '.webm'],
  image: ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'],
}

function getFileCategory(filename: string): string {
  const ext = '.' + filename.split('.').pop()?.toLowerCase()
  for (const [category, extensions] of Object.entries(FILE_CATEGORIES)) {
    if (extensions.includes(ext)) return category
  }
  return 'other'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function ChallengeInput({ onSubmit, onError, disabled }: ChallengeInputProps) {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function handleFile(f: File) {
    if (f.size > MAX_FILE_SIZE) {
      onError(new Error(`File too large. Maximum size is ${MAX_FILE_SIZE / 1024 / 1024}MB.`))
      return
    }
    if (f.size === 0) {
      onError(new Error('File is empty.'))
      return
    }
    setFile(f)
  }

  function clearFile() {
    setFile(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (loading) return

    const hasText = text.trim().length > 0
    const hasFile = file !== null

    if (!hasText && !hasFile) return

    setLoading(true)
    try {
      let response: ChallengeAnalysisResponse

      if (hasFile) {
        // File upload with optional text instructions
        response = await uploadChallengeFile(file, 'default', text.trim())
      } else {
        // Text-only challenge
        response = await submitChallenge(text.trim())
      }

      onSubmit(response)
      setText('')
      clearFile()
    } catch (error) {
      onError(error instanceof Error ? error : new Error('Failed to submit'))
    } finally {
      setLoading(false)
    }
  }

  const isOverLimit = text.length > MAX_CHARACTERS
  const hasInput = text.trim().length > 0 || file !== null
  const canSubmit = hasInput && !loading && !disabled && !isOverLimit

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Submit Challenge</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Text input */}
          <div>
            <label htmlFor="challenge" className="block text-sm font-medium text-gray-700 mb-1">
              {file ? 'Instructions (optional)' : 'Describe the task or challenge'}
            </label>
            <textarea
              id="challenge"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={
                file
                  ? 'Add instructions for how to process the file...'
                  : 'Enter your challenge here, or attach a file below...'
              }
              className="w-full min-h-[120px] px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y text-sm"
              disabled={disabled || loading}
            />
          </div>

          {/* File attachment area */}
          <div
            className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors ${
              dragActive ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200'
            } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-gray-400'}`}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => { e.preventDefault(); setDragActive(false); if (e.dataTransfer.files?.[0]) handleFile(e.dataTransfer.files[0]) }}
            onClick={() => !disabled && inputRef.current?.click()}
          >
            <input
              ref={inputRef}
              type="file"
              onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
              className="hidden"
              disabled={disabled || loading}
            />
            {file ? (
              <div className="flex items-center justify-between px-2">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-indigo-100 rounded flex items-center justify-center">
                    <span className="text-xs font-medium text-indigo-600 uppercase">
                      {file.name.split('.').pop()}
                    </span>
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-medium truncate max-w-[300px]">{file.name}</p>
                    <p className="text-xs text-gray-500">
                      {formatFileSize(file.size)} &middot; {getFileCategory(file.name)}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={(e) => { e.stopPropagation(); clearFile() }}
                  disabled={loading}
                >
                  Remove
                </Button>
              </div>
            ) : (
              <div className="py-2">
                <p className="text-sm text-gray-500">
                  Drag & drop a file, or <span className="text-indigo-600 font-medium">click to browse</span>
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  PDF, Word, Excel, Audio, Video, Images, Text &middot; Max 50MB
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex justify-between items-center">
            <span className={`text-xs ${isOverLimit ? 'text-red-500 font-medium' : 'text-gray-400'}`}>
              {text.length > 0 && `${text.length.toLocaleString()} / ${MAX_CHARACTERS.toLocaleString()}`}
            </span>
            <Button type="submit" disabled={!canSubmit}>
              {loading ? 'Processing...' : file ? 'Upload & Analyze' : 'Submit Challenge'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
