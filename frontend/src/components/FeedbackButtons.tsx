import { useState } from 'react'
import { submitFeedback } from '../api/client'
import { describeError } from '../lib/errors'
import { ThumbDownIcon, ThumbUpIcon } from './icons'

interface Props {
  ticketId: number
  /** Existing verdict, or null if none yet. */
  initial: boolean | null
  /** Show a "Was this diagnosis correct?" prompt next to the buttons. */
  withLabel?: boolean
}

/** Thumbs up/down for one ticket. Updates optimistically and rolls back if saving fails. */
export function FeedbackButtons({ ticketId, initial, withLabel = false }: Props) {
  const [value, setValue] = useState<boolean | null>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function choose(wasCorrect: boolean) {
    if (busy || value === wasCorrect) return
    const previous = value
    setValue(wasCorrect) // optimistic
    setBusy(true)
    setError(null)
    try {
      await submitFeedback(ticketId, wasCorrect)
    } catch (err) {
      setValue(previous)
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const button = (wasCorrect: boolean, label: string, testId: string) => {
    const active = value === wasCorrect
    return (
      <button
        type="button"
        onClick={() => void choose(wasCorrect)}
        disabled={busy}
        aria-pressed={active}
        aria-label={label}
        title={label}
        data-testid={testId}
        className={`inline-flex h-8 w-8 items-center justify-center rounded-md ring-1 ring-inset transition-colors disabled:opacity-60 ${
          active
            ? 'bg-accent-600 text-white ring-accent-600'
            : 'bg-white text-slate-500 ring-slate-300 hover:bg-slate-50 hover:text-slate-800'
        }`}
      >
        {wasCorrect ? <ThumbUpIcon className="h-4 w-4" /> : <ThumbDownIcon className="h-4 w-4" />}
      </button>
    )
  }

  return (
    <div className="inline-flex flex-wrap items-center gap-2">
      {withLabel && <span className="text-sm text-slate-600">Was this diagnosis correct?</span>}
      {button(true, 'Mark diagnosis as correct', 'feedback-up')}
      {button(false, 'Mark diagnosis as incorrect', 'feedback-down')}
      {error && (
        <span role="alert" className="text-xs text-red-700">
          Couldn&apos;t save feedback. {error}
        </span>
      )}
    </div>
  )
}
