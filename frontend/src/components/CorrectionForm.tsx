import { useState, type FormEvent } from 'react'
import { ApiError, correctTicket } from '../api/client'
import { EQUIPMENT_TYPES } from '../lib/equipment'
import { describeError } from '../lib/errors'
import type { ReviewResponse } from '../types/api'
import { SpinnerIcon } from './icons'

const MIN = 5 // mirrors the backend: 5-2000 characters

interface Props {
  ticketId: number
  /** Prefilled (editable): the AI's answer, or the technician's earlier correction. */
  initialRootCause: string
  initialFix: string
  onSaved: (response: ReviewResponse) => void
  onCancel: () => void
}

/** Inline form where a technician records what was really wrong and what really fixed it. */
export function CorrectionForm({ ticketId, initialRootCause, initialFix, onSaved, onCancel }: Props) {
  const [rootCause, setRootCause] = useState(initialRootCause)
  const [fix, setFix] = useState(initialFix)
  const [equipmentType, setEquipmentType] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [serverError, setServerError] = useState<unknown>(null)

  const causeError =
    (submitted && rootCause.trim().length < MIN && `Describe the actual root cause (at least ${MIN} characters).`) ||
    (serverError instanceof ApiError ? serverError.fieldMessage('root_cause') : undefined)
  const fixError =
    (submitted && fix.trim().length < MIN && `Describe the actual fix (at least ${MIN} characters).`) ||
    (serverError instanceof ApiError ? serverError.fieldMessage('recommended_fix') : undefined)
  const showBanner = serverError !== null && !(serverError instanceof ApiError && serverError.kind === 'validation')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSubmitted(true)
    if (busy || rootCause.trim().length < MIN || fix.trim().length < MIN) return
    setBusy(true)
    setServerError(null)
    try {
      onSaved(
        await correctTicket(ticketId, {
          root_cause: rootCause.trim(),
          recommended_fix: fix.trim(),
          equipment_type: equipmentType.trim() || null,
        }),
      )
    } catch (err) {
      setServerError(err)
    } finally {
      setBusy(false)
    }
  }

  const field =
    'mt-1 block w-full rounded-md border px-2.5 py-1.5 text-sm text-slate-900 shadow-sm focus:border-accent-500 disabled:bg-slate-50'

  return (
    <form
      onSubmit={(e) => void submit(e)}
      noValidate
      className="space-y-3 rounded-lg border border-accent-300 bg-sky-50/60 p-3.5"
      data-testid="correction-form"
    >
      <p className="text-sm font-semibold text-navy-900">Record what it really was</p>
      <p className="text-xs text-slate-600">
        Your version is stored next to the AI&apos;s original and added to the knowledge base, so similar
        reports can find it. Only submit what you are confident is right.
      </p>

      <div>
        <label htmlFor={`cause-${ticketId}`} className="text-xs font-semibold uppercase tracking-wide text-slate-600">
          Actual root cause
        </label>
        <textarea
          id={`cause-${ticketId}`}
          rows={3}
          maxLength={2000}
          value={rootCause}
          disabled={busy}
          onChange={(e) => setRootCause(e.target.value)}
          aria-invalid={causeError ? true : undefined}
          data-testid="correction-root-cause"
          className={`${field} ${causeError ? 'border-red-400 bg-red-50/40' : 'border-slate-300'}`}
        />
        {causeError && (
          <p role="alert" className="mt-0.5 text-xs text-red-700" data-testid="correction-root-cause-error">
            {causeError}
          </p>
        )}
      </div>

      <div>
        <label htmlFor={`fix-${ticketId}`} className="text-xs font-semibold uppercase tracking-wide text-slate-600">
          Actual fix
        </label>
        <textarea
          id={`fix-${ticketId}`}
          rows={3}
          maxLength={2000}
          value={fix}
          disabled={busy}
          onChange={(e) => setFix(e.target.value)}
          aria-invalid={fixError ? true : undefined}
          data-testid="correction-fix"
          className={`${field} ${fixError ? 'border-red-400 bg-red-50/40' : 'border-slate-300'}`}
        />
        {fixError && (
          <p role="alert" className="mt-0.5 text-xs text-red-700" data-testid="correction-fix-error">
            {fixError}
          </p>
        )}
      </div>

      <div>
        <label htmlFor={`type-${ticketId}`} className="text-xs font-semibold uppercase tracking-wide text-slate-600">
          Equipment type <span className="font-normal normal-case text-slate-500">(optional)</span>
        </label>
        {/* Free text with suggestions: the knowledge base is not limited to the six seed families. */}
        <input
          id={`type-${ticketId}`}
          type="text"
          list={`types-${ticketId}`}
          maxLength={64}
          value={equipmentType}
          disabled={busy}
          onChange={(e) => setEquipmentType(e.target.value)}
          placeholder="e.g. forklift, pump, HVAC"
          data-testid="correction-equipment-type"
          className={`${field} border-slate-300 bg-white sm:w-56`}
        />
        <datalist id={`types-${ticketId}`}>
          {EQUIPMENT_TYPES.map((type) => (
            <option key={type} value={type} />
          ))}
        </datalist>
      </div>

      {showBanner && (
        <p role="alert" className="text-sm text-red-700" data-testid="correction-error">
          {describeError(serverError).message}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={busy}
          data-testid="correction-submit"
          className="inline-flex items-center gap-1.5 rounded-md bg-accent-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent-700 disabled:opacity-70"
        >
          {busy && <SpinnerIcon className="h-4 w-4" />}
          Save correction &amp; add to knowledge base
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}
