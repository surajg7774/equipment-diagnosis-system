import { useEffect, useRef, useState } from 'react'
import { ACCEPTED_IMAGE_TYPES, photoProblem } from '../lib/photo'
import { formatBytes } from '../lib/format'
import { ImageIcon } from './icons'

interface Props {
  file: File | null
  onChange: (file: File | null) => void
  disabled?: boolean
}

/**
 * "Attach a photo (optional)" for the main diagnosis form. The photo is sent together with the
 * description and analysed as part of the SAME diagnosis (the standalone "Diagnose from a photo" card is
 * for people who only have a photo). Shows a thumbnail with a remove button once a photo is chosen.
 */
export function PhotoAttachment({ file, onChange, disabled = false }: Props) {
  const [problem, setProblem] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const previewRef = useRef<string | null>(null) // lets us free the object URL on change, remove and unmount

  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    },
    [],
  )

  function releasePreview() {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    previewRef.current = null
    setPreviewUrl(null)
  }

  function pick(picked: File | undefined) {
    setProblem(null)
    if (!picked) return
    const reason = photoProblem(picked)
    if (reason) {
      setProblem(reason)
      if (inputRef.current) inputRef.current.value = ''
      return
    }
    releasePreview()
    previewRef.current = URL.createObjectURL(picked)
    setPreviewUrl(previewRef.current)
    onChange(picked)
  }

  function remove() {
    setProblem(null)
    releasePreview()
    if (inputRef.current) inputRef.current.value = ''
    onChange(null)
  }

  return (
    <div data-testid="photo-attachment">
      <div className="flex flex-wrap items-center gap-3">
        <label
          className={`inline-flex items-center gap-2 rounded-md bg-white px-3 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 ${
            disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-slate-50'
          }`}
        >
          <ImageIcon className="h-4 w-4" />
          {file ? 'Change photo' : 'Attach a photo (optional)'}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_IMAGE_TYPES.join(',')}
            className="sr-only"
            data-testid="photo-input"
            disabled={disabled}
            onChange={(e) => pick(e.target.files?.[0])}
          />
        </label>

        {file && previewUrl && (
          <div className="flex items-center gap-2" data-testid="photo-preview">
            <img src={previewUrl} alt="Attached photo preview" className="h-12 w-12 rounded-md object-cover ring-1 ring-slate-300" />
            <span className="text-xs text-slate-600">
              {file.name}
              <br />
              {formatBytes(file.size)}
            </span>
            <button
              type="button"
              onClick={remove}
              disabled={disabled}
              data-testid="photo-remove"
              className="rounded-md px-2 py-1 text-xs font-medium text-slate-600 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:opacity-60"
            >
              Remove
            </button>
          </div>
        )}
      </div>

      {problem && (
        <p role="alert" className="mt-1.5 text-xs text-red-700" data-testid="photo-error">
          {problem}
        </p>
      )}
      <p className="mt-1.5 text-xs text-slate-500">
        {file
          ? 'The AI will look at this photo together with your description and give one diagnosis.'
          : 'Optional: a photo of the problem helps the AI see what you describe.'}
      </p>
    </div>
  )
}
