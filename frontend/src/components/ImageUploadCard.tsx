import { useEffect, useRef, useState } from 'react'
import { diagnoseImage } from '../api/client'
import { formatBytes } from '../lib/format'
import { ACCEPTED_IMAGE_TYPES, MAX_IMAGE_BYTES, PHOTO_CAVEAT } from '../lib/photo'
import type { ImageDiagnoseResponse } from '../types/api'
import { ConfidenceBar } from './ConfidenceBar'
import { ErrorBanner } from './ErrorBanner'
import { SeverityBadge } from './SeverityBadge'
import { AlertIcon, CheckCircleIcon, ImageIcon, InfoIcon, SpinnerIcon } from './icons'

// Shared with the "Attach a photo" control on the main form (lib/photo.ts).
const ACCEPTED_TYPES = ACCEPTED_IMAGE_TYPES
const MAX_BYTES = MAX_IMAGE_BYTES
const CAVEAT = PHOTO_CAVEAT

type Status =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'success'; data: ImageDiagnoseResponse }
  | { phase: 'error'; error: unknown }

function Finding({ title, children, testId }: { title: string; children: string; testId: string }) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
      <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-slate-800" data-testid={testId}>
        {children}
      </p>
    </div>
  )
}

/** The model's assessment of one photo. Not-equipment photos get a neutral card (nothing is stored). */
function ImageResult({ data }: { data: ImageDiagnoseResponse }) {
  if (!data.is_equipment_photo) {
    return (
      <div className="space-y-3 rounded-lg border border-slate-300 bg-slate-50 p-4" data-testid="image-result" data-kind="not-equipment">
        <div className="flex items-start gap-2.5">
          <InfoIcon className="mt-0.5 h-5 w-5 shrink-0 text-slate-500" />
          <div>
            <p className="font-semibold text-slate-800">This doesn&apos;t look like equipment</p>
            <p className="text-sm text-slate-600">The AI couldn&apos;t treat this photo as something to inspect.</p>
          </div>
        </div>
        <Finding title="What the AI sees" testId="image-description">
          {data.description}
        </Finding>
        <Finding title="Suggested next step" testId="image-action">
          {data.recommended_action}
        </Finding>
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700" data-testid="image-no-ticket">
          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-slate-700">
            No ticket created
          </span>
          <span>{data.note ?? 'This photo was not saved to ticket history.'}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4" data-testid="image-result" data-kind="equipment">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {data.damage_detected ? (
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-900 ring-1 ring-inset ring-amber-400/60"
            data-testid="image-damage-chip"
            data-damage="true"
          >
            <AlertIcon className="h-3.5 w-3.5" />
            Possible damage detected
          </span>
        ) : (
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 ring-1 ring-inset ring-slate-300"
            data-testid="image-damage-chip"
            data-damage="false"
          >
            <CheckCircleIcon className="h-3.5 w-3.5" />
            No visible damage
          </span>
        )}
        <div className="flex items-center gap-2">
          {data.ticket_id !== null && (
            <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600" data-testid="image-ticket-id">
              Ticket #{data.ticket_id}
            </span>
          )}
          {data.severity !== null && <SeverityBadge severity={data.severity} />}
        </div>
      </div>

      <Finding title="What the AI sees" testId="image-description">
        {data.description}
      </Finding>
      <div className="border-l-4 border-accent-500 pl-3">
        <Finding title="Recommended action" testId="image-action">
          {data.recommended_action}
        </Finding>
      </div>

      {data.confidence !== null && (
        <ConfidenceBar
          score={data.confidence}
          label="AI confidence"
          caption="The model's own certainty in this assessment. A rough guide only: a photo cannot show internal faults."
        />
      )}

      <p className="border-t border-slate-100 pt-3 text-xs text-slate-500" data-testid="image-model">
        Assessed by {data.model_name} ({data.provider}). {CAVEAT}
      </p>
    </div>
  )
}

/**
 * Photo diagnosis: a vision-language model describes visible damage, wear, leaks and corrosion.
 * It is a general-purpose model, so every view of the card carries the "not a substitute for
 * professional inspection" caveat.
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
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="image-heading" data-testid="image-card">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="image-heading" className="text-base font-semibold text-navy-900">
          Diagnose from a photo
        </h2>
        <span className="rounded bg-sky-100 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-sky-900 ring-1 ring-inset ring-accent-500/40">
          AI vision
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        An AI vision model looks at your photo and describes any visible damage, wear, leaks or corrosion.
      </p>
      <p className="mt-2 flex items-start gap-1.5 rounded-md bg-slate-50 px-2.5 py-2 text-xs text-slate-600 ring-1 ring-inset ring-slate-200" data-testid="image-caveat">
        <InfoIcon className="mt-px h-3.5 w-3.5 shrink-0 text-slate-400" />
        {CAVEAT}
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
          {loading ? 'Analyzing photo…' : 'Analyze photo'}
        </button>
      )}

      {status.phase === 'error' && <ErrorBanner className="mt-4" error={status.error} onRetry={() => void analyze()} />}
      {status.phase === 'success' && (
        <div className="mt-4" aria-live="polite">
          <ImageResult data={status.data} />
        </div>
      )}
    </section>
  )
}
