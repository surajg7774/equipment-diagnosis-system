import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, diagnose } from '../api/client'
import { ErrorBanner } from '../components/ErrorBanner'
import { ImageUploadCard } from '../components/ImageUploadCard'
import { InvalidResultCard } from '../components/ResultCard'
import { ResultSkeleton } from '../components/ResultSkeleton'
import { SessionFlow } from '../components/SessionFlow'
import { SpinnerIcon } from '../components/icons'
import { EQUIPMENT_TYPES } from '../lib/equipment'
import { useElapsedSeconds } from '../lib/useElapsedSeconds'
import type { DiagnoseResponse } from '../types/api'

// Mirrors the backend's validation: description is 10-2000 characters after trimming.
const MIN_LENGTH = 10
const MAX_LENGTH = 2000


// The equipment type is sent as its own field (never merged into the description, so the stored
// report is exactly what was typed). It also picks a placeholder that suggests what to describe.
const MAX_TYPE_LENGTH = 64
const DEFAULT_PLACEHOLDER = 'e.g. pump making loud grinding noise and leaking oil'
const PLACEHOLDERS: Record<string, string> = {
  pump: 'e.g. loud grinding noise and oil leaking near the shaft seal',
  motor: 'e.g. overheating with a burning smell, breaker keeps tripping',
  printer: 'e.g. paper jams and toner smears, fuser error on the display',
  HVAC: 'e.g. blowing warm air, water dripping from the indoor unit',
  'conveyor belt': 'e.g. belt drifting to one side and slipping on the drive pulley',
  generator: 'e.g. cranks slowly and will not start, black smoke when running',
  laptop: 'e.g. battery drains in an hour and the fan is loud',
  'mobile phone': 'e.g. will not turn on even after charging overnight',
}

const EXAMPLES = [
  'pump making loud grinding noise and leaking oil',
  'my mobile phone will not turn on even after charging',
  'forklift hydraulics leaking fluid and losing lift power',
  'what is the capital of France',
]

type Status =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'success'; data: DiagnoseResponse }
  | { phase: 'error'; error: unknown }

export function DiagnosePage() {
  const [text, setText] = useState('')
  const [equipmentType, setEquipmentType] = useState('')
  const [submitted, setSubmitted] = useState(false) // show client validation after the first attempt
  const [status, setStatus] = useState<Status>({ phase: 'idle' })
  const controllerRef = useRef<AbortController | null>(null)
  const lastRequestRef = useRef<string | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  const loading = status.phase === 'loading'
  const elapsed = useElapsedSeconds(loading)
  const trimmedLength = text.trim().length

  useEffect(() => () => controllerRef.current?.abort(), [])

  // Client-side check, shown inline before anything is sent.
  const clientError =
    submitted && trimmedLength < MIN_LENGTH
      ? `Please describe the problem in at least ${MIN_LENGTH} characters (currently ${trimmedLength}).`
      : null
  // Server-side 422 for this field (e.g. something the client check can't see).
  const serverFieldError =
    status.phase === 'error' && status.error instanceof ApiError ? status.error.fieldMessage('description') : undefined
  const fieldError = clientError ?? serverFieldError
  // 422s that were already shown on the field must not also appear as a banner.
  const showBanner = status.phase === 'error' && !serverFieldError

  async function run(description: string) {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    lastRequestRef.current = description
    setStatus({ phase: 'loading' })
    try {
      const data = await diagnose(description, controller.signal, equipmentType.trim() || undefined)
      setStatus({ phase: 'success', data })
      // Bring the result into view on small screens where it renders below the form.
      requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
    } catch (error) {
      if (controller.signal.aborted) return
      setStatus({ phase: 'error', error })
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitted(true)
    if (loading || trimmedLength < MIN_LENGTH) return
    // The description is sent exactly as typed; the equipment type travels separately.
    void run(text.trim())
  }

  function onRetry() {
    if (lastRequestRef.current) void run(lastRequestRef.current)
  }

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      {/* ---- Left: input ---- */}
      <div className="space-y-6 lg:col-span-2">
        <form onSubmit={onSubmit} noValidate className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div>
            <label htmlFor="description" className="block text-sm font-semibold text-navy-900">
              Describe the problem
            </label>
            <textarea
              id="description"
              name="description"
              rows={6}
              maxLength={MAX_LENGTH}
              value={text}
              disabled={loading}
              onChange={(e) => {
                setText(e.target.value)
                if (status.phase === 'error') setStatus({ phase: 'idle' })
              }}
              placeholder={PLACEHOLDERS[equipmentType.trim()] ?? DEFAULT_PLACEHOLDER}
              aria-invalid={fieldError ? true : undefined}
              aria-describedby="description-help description-error"
              data-testid="description"
              className={`mt-1.5 block w-full resize-y rounded-lg border px-3 py-2 text-[15px] text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-accent-500 disabled:bg-slate-50 ${
                fieldError ? 'border-red-400 bg-red-50/40' : 'border-slate-300'
              }`}
            />
            <div className="mt-1 flex items-start justify-between gap-3 text-xs">
              <p id="description-error" role="alert" className="text-red-700" data-testid="description-error">
                {fieldError}
              </p>
              <p id="description-help" className="ml-auto shrink-0 text-slate-500">
                {trimmedLength < MIN_LENGTH ? `Min ${MIN_LENGTH} characters` : `${trimmedLength} characters`}
              </p>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-500">Try:</span>
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  disabled={loading}
                  onClick={() => {
                    setText(example)
                    setStatus({ phase: 'idle' })
                  }}
                  className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-200 disabled:opacity-60"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label htmlFor="equipment-type" className="block text-sm font-semibold text-navy-900">
              Equipment type <span className="font-normal text-slate-500">(optional)</span>
            </label>
            <input
              id="equipment-type"
              type="text"
              list="equipment-type-suggestions"
              value={equipmentType}
              maxLength={MAX_TYPE_LENGTH}
              disabled={loading}
              onChange={(e) => setEquipmentType(e.target.value)}
              placeholder="e.g. laptop, pump, washing machine"
              autoComplete="off"
              data-testid="equipment-type"
              className="mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-accent-500 disabled:bg-slate-50"
            />
            <datalist id="equipment-type-suggestions">
              {EQUIPMENT_TYPES.map((type) => (
                <option key={type} value={type} />
              ))}
            </datalist>
            <p className="mt-1 text-xs text-slate-500">
              Any kind of device or machine works. Saved with your report; it does not change the diagnosis.
            </p>
          </div>

          <button
            type="submit"
            disabled={loading}
            data-testid="submit"
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-accent-700 disabled:cursor-not-allowed disabled:opacity-80"
          >
            {loading && <SpinnerIcon className="h-4 w-4" />}
            {loading ? `Analyzing… ${elapsed}s` : 'Diagnose'}
          </button>
        </form>

        <ImageUploadCard />
      </div>

      {/* ---- Right: result ---- */}
      <div className="lg:col-span-3" ref={resultRef} aria-live="polite">
        {(status.phase === 'idle' || (status.phase === 'error' && !showBanner)) && (
          <div className="rounded-xl border-2 border-dashed border-slate-300 p-8 text-center text-slate-500" data-testid="empty-result">
            <p className="font-medium text-slate-700">Your diagnosis will appear here</p>
            <p className="mt-1 text-sm">
              Describe what's wrong with the equipment. The assistant compares it with past cases and suggests a cause and
              next step.
            </p>
          </div>
        )}

        {loading && <ResultSkeleton seconds={elapsed} />}

        {showBanner && status.phase === 'error' && <ErrorBanner error={status.error} onRetry={onRetry} />}

        {status.phase === 'success' &&
          (status.data.is_valid_issue ? (
            // key: a new diagnosis starts a fresh session view instead of reusing the old one's state
            <SessionFlow key={status.data.session_id ?? status.data.ticket_id ?? 'result'} first={status.data} />
          ) : (
            <InvalidResultCard data={status.data} />
          ))}
      </div>
    </div>
  )
}
