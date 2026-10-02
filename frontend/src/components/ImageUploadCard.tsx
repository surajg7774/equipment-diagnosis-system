import { useEffect, useRef, useState } from 'react'
import { diagnoseImage } from '../api/client'
import { formatBytes } from '../lib/format'
import type { ImageDiagnoseResponse } from '../types/api'
import { ConfidenceBar } from './ConfidenceBar'
import { ErrorBanner } from './ErrorBanner'
import { SeverityBadge } from './SeverityBadge'
import { AlertIcon, ImageIcon, SpinnerIcon } from './icons'

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_BYTES = 5 * 1024 * 1024 // matches the backend default; the backend still enforces its own limit

type Status =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'success'; data: ImageDiagnoseResponse }
  | { phase: 'error'; error: unknown }

/**
 * Optional photo diagnosis. The backend currently answers from a PLACEHOLDER model that
 * does not analyse the image, so this card is labelled experimental everywhere it appears.
 */
export function ImageUploadCard() {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [status, setStatus] = useState<Status>({ phase: 'idle' })
  const inputRef = useRef<HTMLInputElement>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const previewRef = useRef<string | null>(null) // lets us revoke the object URL on change/unmount

  // On unmount: cancel any in-flight request and free the preview URL.
  useEffect(
    () => () => {
      controllerRef.current?.abort()
      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    },
    [],
  )

  function onPick(picked: File | undefined) {
    setStatus({ phase: 'idle' })
    setFileError(null)
    if (!picked) return
    if (!ACCEPTED_TYPES.includes(picked.type)) {
      setFileError('Please choose a JPEG, PNG or WebP image.')
      return clear()
    }
    if (picked.size > MAX_BYTES) {
      setFileError(`That image is ${formatBytes(picked.size)}. The limit is ${formatBytes(MAX_BYTES)}.`)
      return clear()
    }
    releasePreview()
    previewRef.current = URL.createObjectURL(picked)
    setPreviewUrl(previewRef.current)
    setFile(picked)
  }

  function releasePreview() {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    previewRef.current = null
  }

  function clear() {
    releasePreview()
    setFile(null)
    setPreviewUrl(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  async function analyze() {
    if (!file) return
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setStatus({ phase: 'loading' })
    try {
      const data = await diagnoseImage(file, controller.signal)
      setStatus({ phase: 'success', data })
    } catch (error) {
      if (controller.signal.aborted) return
      setStatus({ phase: 'error', error })
    }
  }

  const loading = status.phase === 'loading'

  return (
    <section
      className="rounded-xl border-2 border-dashed border-slate-300 bg-white/60 p-5"
      aria-labelledby="image-heading"
      data-testid="image-card"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="image-heading" className="text-base font-semibold text-navy-900">
          Diagnose from a photo
        </h2>
        <span className="rounded bg-amber-100 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-amber-900 ring-1 ring-inset ring-amber-500/40">
          Experimental
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        Placeholder feature: the backend currently uses a stand-in model that <strong>does not actually analyze</strong>{' '}
        the image, so results are not real predictions.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-white px-3 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
          <ImageIcon className="h-4 w-4" />
          {file ? 'Choose a different photo' : 'Choose a photo'}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_TYPES.join(',')}
            className="sr-only"
            data-testid="image-input"
            disabled={loading}
            onChange={(e) => onPick(e.target.files?.[0])}
          />
        </label>
        {file && previewUrl && (
          <div className="flex items-center gap-2">
            <img src={previewUrl} alt="Selected equipment photo" className="h-12 w-12 rounded-md object-cover ring-1 ring-slate-300" />
            <span className="text-xs text-slate-600">
              {file.name}
              <br />
              {formatBytes(file.size)}
            </span>
          </div>
        )}
      </div>

      {fileError && (
        <p role="alert" className="mt-2 text-sm text-red-700" data-testid="image-file-error">
          {fileError}
        </p>
      )}

      {file && (
        <button
          type="button"
          onClick={() => void analyze()}
          disabled={loading}
          data-testid="image-submit"
          className="mt-3 inline-flex items-center gap-2 rounded-md bg-navy-800 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-700 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {loading && <SpinnerIcon className="h-4 w-4" />}
          {loading ? 'Analyzing photo…' : 'Analyze photo (experimental)'}
        </button>
      )}

      {status.phase === 'error' && <ErrorBanner className="mt-4" error={status.error} onRetry={() => void analyze()} />}

      {status.phase === 'success' && (
        <div className="mt-4 space-y-3 rounded-lg border border-slate-200 bg-white p-4" data-testid="image-result">
          {status.data.is_placeholder && (
            <div className="flex gap-2 rounded-md border-2 border-dashed border-amber-400 bg-amber-50 p-2.5 text-sm text-amber-950">
              <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <span>
                <strong>Placeholder result.</strong> Produced by &ldquo;{status.data.model_name}&rdquo;, which does not
                look at the image. Do not rely on it.
              </span>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium text-slate-800">{status.data.diagnosis}</p>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600">
                Ticket #{status.data.ticket_id}
              </span>
              <SeverityBadge severity={status.data.severity} />
            </div>
          </div>
          <p className="text-sm text-slate-700">{status.data.recommended_action}</p>
          <ConfidenceBar
            score={status.data.confidence_score}
            label={status.data.is_placeholder ? 'Confidence (fixed placeholder value)' : 'Confidence'}
          />
        </div>
      )}
    </section>
  )
}
