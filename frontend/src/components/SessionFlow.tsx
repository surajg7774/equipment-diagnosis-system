import { useEffect, useRef, useState } from 'react'
import { sendSessionFeedback } from '../api/client'
import { useElapsedSeconds } from '../lib/useElapsedSeconds'
import type { DiagnoseResponse } from '../types/api'
import { ErrorBanner } from './ErrorBanner'
import { ResultCard } from './ResultCard'
import { CheckCircleIcon, InfoIcon, SpinnerIcon } from './icons'

/** Where the "try a solution, give feedback, get the next one" loop currently is. */
type Phase =
  | { kind: 'asking' } // a solution is showing and we are waiting for the user's answer
  | { kind: 'working'; verdict: boolean } // an answer is being sent (a "no" waits for a new LLM solution)
  | { kind: 'resolved'; message: string | null; addedToKb: boolean }
  | { kind: 'escalated'; message: string | null }

/**
 * One diagnosis session: shows the current solution with "Did this solve it?", swaps in a different
 * solution after each "No", keeps the earlier attempts in a collapsible list, and ends with either a
 * clear "Resolved!" or (at the attempt cap) a calm "please escalate to a human technician" notice.
 */
export function SessionFlow({ first }: { first: DiagnoseResponse }) {
  const [attempts, setAttempts] = useState<DiagnoseResponse[]>([first])
  const [phase, setPhase] = useState<Phase>({ kind: 'asking' })
  const [error, setError] = useState<unknown>(null)
  const lastVerdictRef = useRef(false)
  const controllerRef = useRef<AbortController | null>(null)
  const topRef = useRef<HTMLDivElement>(null)

  const working = phase.kind === 'working'
  const waitingForNewSolution = phase.kind === 'working' && !phase.verdict
  const elapsed = useElapsedSeconds(waitingForNewSolution)

  useEffect(() => () => controllerRef.current?.abort(), [])

  // Bring a new solution into view (on small screens it can render below the fold).
  useEffect(() => {
    if (attempts.length > 1) topRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [attempts.length])

  const current = attempts[attempts.length - 1]
  const sessionId = first.session_id
  // A backend that predates sessions sends no session id: show the diagnosis without the question.
  if (!sessionId) return <ResultCard data={first} />

  const attemptNumber = current.attempt_number ?? attempts.length
  const maxAttempts = current.max_attempts ?? first.max_attempts ?? 4
  const attemptsLeft = Math.max(0, maxAttempts - attemptNumber)
  const previous = attempts.slice(0, -1)

  async function answer(verdict: boolean) {
    if (working) return
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    lastVerdictRef.current = verdict
    setError(null)
    setPhase({ kind: 'working', verdict })
    try {
      const response = await sendSessionFeedback(sessionId!, verdict, attemptNumber, controller.signal)
      if (response.next_attempt) {
        setAttempts((all) => [...all, response.next_attempt!])
        setPhase({ kind: 'asking' })
      } else if (response.resolved) {
        setPhase({ kind: 'resolved', message: response.message, addedToKb: response.added_to_knowledge_base })
      } else if (response.escalate) {
        setPhase({ kind: 'escalated', message: response.message })
      } else {
        setPhase({ kind: 'asking' })
      }
    } catch (err) {
      if (controller.signal.aborted) return
      setError(err)
      setPhase({ kind: 'asking' }) // the same question stays available: nothing was saved on failure
    }
  }

  return (
    <div className="space-y-4" ref={topRef} data-testid="session-flow" data-phase={phase.kind} data-attempt={attemptNumber}>
      <ResultCard data={current} footer={renderFooter()} />
      {previous.length > 0 && <PreviousAttempts attempts={previous} />}
    </div>
  )

  // A plain function (not a component): it must not remount, and lose focus, on every render.
  function renderFooter() {
    if (phase.kind === 'resolved') {
      return (
        <div className="flex gap-3 rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-emerald-950" role="status" data-testid="resolved-banner">
          <CheckCircleIcon className="mt-0.5 h-6 w-6 shrink-0 text-emerald-600" />
          <div>
            <p className="text-base font-semibold">Resolved!</p>
            <p className="mt-0.5 text-sm text-emerald-900/90" data-testid="resolved-message">
              {phase.message ?? 'Glad that fixed it.'}
            </p>
            {phase.addedToKb && (
              <p className="mt-1 text-xs text-emerald-800/80" data-testid="added-to-kb">
                This solution was added to the knowledge base to help with similar problems.
              </p>
            )}
          </div>
        </div>
      )
    }

    if (phase.kind === 'escalated') {
      return (
        <div className="flex gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950" role="status" data-testid="escalate-notice">
          <InfoIcon className="mt-0.5 h-6 w-6 shrink-0 text-amber-600" />
          <div>
            <p className="text-base font-semibold">Please escalate this to a human technician</p>
            <p className="mt-0.5 text-sm text-amber-900/90">
              {phase.message ?? `None of the ${maxAttempts} suggested solutions worked.`}
            </p>
            <p className="mt-1 text-xs text-amber-800/80">
              Share the solutions that were already tried (listed below) so they do not repeat them.
            </p>
          </div>
        </div>
      )
    }

    return (
      <div data-testid="solve-question">
        <p className="text-sm font-semibold text-navy-900">Did this solve it?</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void answer(true)}
            disabled={working}
            data-testid="solved-yes"
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {phase.kind === 'working' && phase.verdict && <SpinnerIcon className="h-4 w-4" />}
            Yes, it&apos;s fixed
          </button>
          <button
            type="button"
            onClick={() => void answer(false)}
            disabled={working}
            data-testid="solved-no"
            className="inline-flex items-center gap-1.5 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {waitingForNewSolution && <SpinnerIcon className="h-4 w-4" />}
            {waitingForNewSolution ? `Finding a different solution… ${elapsed}s` : 'No, try something else'}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500" data-testid="attempts-left">
          {attemptsLeft > 0
            ? `If not, the assistant will suggest a different cause and fix (${attemptsLeft} more available).`
            : 'This is the last automatic suggestion. If it does not work you will be pointed to a human technician.'}
        </p>
        {error !== null && (
          <ErrorBanner className="mt-3" error={error} onRetry={() => void answer(lastVerdictRef.current)} />
        )}
      </div>
    )
  }
}

/** Earlier attempts (all of which did not work), collapsed by default. */
function PreviousAttempts({ attempts }: { attempts: DiagnoseResponse[] }) {
  return (
    <details className="rounded-xl border border-slate-200 bg-white shadow-sm" data-testid="previous-attempts">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-semibold text-slate-700">
        Previous attempts that did not work ({attempts.length})
      </summary>
      <ol className="space-y-3 border-t border-slate-100 px-4 py-3">
        {attempts.map((a) => (
          <li key={a.attempt_number} className="rounded-lg bg-slate-50 p-3 text-sm" data-testid="previous-attempt">
            <p className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Attempt {a.attempt_number}
              <span className="rounded bg-slate-200 px-1.5 py-0.5 normal-case text-slate-600">Did not work</span>
            </p>
            <p className="mt-1.5 text-slate-800">
              <span className="font-medium">Cause: </span>
              {a.diagnosis}
            </p>
            <p className="mt-1 whitespace-pre-line text-slate-700">
              <span className="font-medium">Action: </span>
              {a.recommended_action}
            </p>
          </li>
        ))}
      </ol>
    </details>
  )
}
