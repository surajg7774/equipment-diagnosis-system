import { useState } from 'react'
import { confirmTicket } from '../api/client'
import { describeError } from '../lib/errors'
import type { FixVerification, ReviewResponse, ReviewStatus } from '../types/api'
import { CheckCircleIcon, PencilIcon, SpinnerIcon } from './icons'

interface Props {
  ticketId: number
  status: ReviewStatus
  /** Whether the ticket's fix in the knowledge base is verified or only provisional (confirmed once by a user). */
  verification?: FixVerification | null
  onReviewed: (response: ReviewResponse) => void
  /** Open the correction form for this ticket. */
  onCorrect: () => void
}

const base =
  'inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset transition-colors disabled:cursor-not-allowed disabled:opacity-60'

/** Confirm / Verify / Correct buttons for one ticket. Which ones appear depends on its current status. */
export function ReviewActions({ ticketId, status, verification, onReviewed, onCorrect }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      onReviewed(await confirmTicket(ticketId))
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {status === 'pending' && (
        <button
          type="button"
          onClick={() => void confirm()}
          disabled={busy}
          title="The AI's diagnosis was correct. This adds the case to the knowledge base."
          data-testid="confirm-button"
          className={`${base} bg-accent-600 text-white ring-accent-600 hover:bg-accent-700`}
        >
          {busy ? <SpinnerIcon className="h-3.5 w-3.5" /> : <CheckCircleIcon className="h-3.5 w-3.5" />}
          Confirm
        </button>
      )}
      {/* An end user already confirmed this fix (a thumbs up or "Yes"): it is provisional until a technician checks it. */}
      {status === 'confirmed' && verification === 'provisional' && (
        <button
          type="button"
          onClick={() => void confirm()}
          disabled={busy}
          title="A user confirmed this fix. As a technician, verify it so it counts as a verified fix in the knowledge base."
          data-testid="verify-button"
          className={`${base} bg-accent-600 text-white ring-accent-600 hover:bg-accent-700`}
        >
          {busy ? <SpinnerIcon className="h-3.5 w-3.5" /> : <CheckCircleIcon className="h-3.5 w-3.5" />}
          Verify
        </button>
      )}
      <button
        type="button"
        onClick={onCorrect}
        disabled={busy}
        title="Enter the actual root cause and fix. The corrected case is added to the knowledge base."
        data-testid="correct-button"
        className={`${base} bg-white text-slate-700 ring-slate-300 hover:bg-slate-50`}
      >
        <PencilIcon className="h-3.5 w-3.5" />
        {status === 'corrected' ? 'Edit correction' : 'Correct…'}
      </button>
      {error && (
        <span role="alert" className="basis-full text-xs text-red-700" data-testid="review-error">
          {error}
        </span>
      )}
    </div>
  )
}
