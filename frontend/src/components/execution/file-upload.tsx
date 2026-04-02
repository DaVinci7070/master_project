'use client'

import { useState, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { uploadChallengeFile } from '@/lib/api'
import type { ChallengeAnalysisResponse } from '@/types'

interface FileUploadProps {
  onSubmit: (response: ChallengeAnalysisResponse) => void
  onError: (error: Error) => void
  disabled?: boolean
}

// Supported file formats with icons
const FILE_CATEGORIES = {
  document: ['.pdf', '.doc', '.docx', '.odt', '.rtf'],
  spreadsheet: ['.xlsx', '.xls', '.csv', '.ods'],
  text: ['.txt', '.md', '.json', '.xml', '.yaml', '.yml'],
  presentation: ['.pptx', '.ppt', '.odp'],
  image: ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'],
  audio: ['.mp3', '.wav', '.m4a', '.ogg', '.opus', '.flac', '.aac'],
  video: ['.mp4', '.mov', '.avi', '.mkv', '.webm'],
}

const MAX_SIZE = 50 * 1024 * 1024 // 50MB for larger files like PDFs and media

export function FileUpload({ onSubmit, onError, disabled }: FileUploadProps) {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function getFileCategory(filename: string): string {
    const ext = '.' + filename.split('.').pop()?.toLowerCase()
    for (const [category, extensions] of Object.entries(FILE_CATEGORIES)) {
      if (extensions.includes(ext)) return category
    }
    return 'other'
  }

  function validateFile(f: File): string | null {
    if (f.size > MAX_SIZE) {
      return `File too large. Maximum size is ${MAX_SIZE / 1024 / 1024}MB.`
    }
    if (f.size === 0) {
      return 'File is empty.'
    }
    return null
  }

  function handleFile(f: File) {
    const error = validateFile(f)
    if (error) {
      onError(new Error(error))
      return
    }
    setFile(f)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragActive(false)
    if (e.dataTransfer.files?.[0]) {
      handleFile(e.dataTransfer.files[0])
    }
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    setDragActive(true)
  }

  function handleDragLeave() {
    setDragActive(false)
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files?.[0]) {
      handleFile(e.target.files[0])
    }
  }

  function handleClick() {
    if (!disabled) {
      inputRef.current?.click()
    }
  }

  function clearFile() {
    setFile(null)
    if (inputRef.current) {
      inputRef.current.value = ''
    }
  }

  async function handleSubmit() {
    if (!file || loading) return

    setLoading(true)
    try {
      const response = await uploadChallengeFile(file)
      onSubmit(response)
      clearFile()
    } catch (error) {
      onError(error instanceof Error ? error : new Error('Failed to upload file'))
    } finally {
      setLoading(false)
    }
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  function getFileIcon(filename: string) {
    const category = getFileCategory(filename)
    const iconMap: Record<string, JSX.Element> = {
      document: (
        <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      ),
      spreadsheet: (
        <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      ),
      text: (
        <svg className="w-6 h-6 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      ),
      image: (
        <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      ),
      audio: (
        <svg className="w-6 h-6 text-orange-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
        </svg>
      ),
      video: (
        <svg className="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      ),
      other: (
        <svg className="w-6 h-6 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
        </svg>
      ),
    }
    return iconMap[category] || iconMap.other
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Upload Challenge File</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            dragActive ? 'border-indigo-500 bg-indigo-50' : 'border-gray-300'
          } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-gray-400'}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={handleClick}
        >
          <input
            ref={inputRef}
            type="file"
            onChange={handleChange}
            className="hidden"
            disabled={disabled || loading}
          />
          {file ? (
            <div className="space-y-2">
              <div className="w-12 h-12 mx-auto bg-indigo-100 rounded-lg flex items-center justify-center">
                {getFileIcon(file.name)}
              </div>
              <p className="font-medium">{file.name}</p>
              <p className="text-sm text-gray-500">{formatFileSize(file.size)}</p>
              <p className="text-xs text-indigo-600 capitalize">{getFileCategory(file.name)} file</p>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="w-12 h-12 mx-auto bg-gray-100 rounded-lg flex items-center justify-center">
                <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
              </div>
              <p className="text-gray-600">Drag and drop any file here, or click to select</p>
              <p className="text-sm text-gray-400">
                Supports: PDF, Word, Excel, Images, Audio, Video, Text, and more
              </p>
              <p className="text-xs text-gray-400">Maximum size: 50MB</p>
            </div>
          )}
        </div>

        {file && (
          <div className="mt-4 flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={(e) => {
                e.stopPropagation()
                clearFile()
              }}
              disabled={loading}
            >
              Clear
            </Button>
            <Button onClick={handleSubmit} disabled={loading || disabled}>
              {loading ? 'Processing...' : 'Submit File'}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
