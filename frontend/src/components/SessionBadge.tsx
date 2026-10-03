import type { SessionOut, SessionStatus } from '../types/api'

const STYLES: Record<SessionStatus, { label: string; className: string }> = {
  in_progress: { label: 'In progress', className: 'bg-sky-50 text-sky-800 ring-sky-200' },
  resolved: { label: 'Resolved', className: 'bg-emerald-50 text-emerald-800 ring-emerald-200' },
  abandoned: { label: 'Needs a human technician', className: 'bg-amber-50 text-amber-900 ring-amber-300' },
}

function attemptsText(session: SessionOut): string {
  const n = session.attempt_count
  if (session.status === 'resolved' && session.attempts_to_resolve !== null) {
    return `resolved in ${session.attempts_to_resolve} attempt${session.attempts_to_resolve === 1 ? '' : 's'}`
  }
  if (session.status === 'abandoned') return `${n} attempts, none worked`
  return `${n} attempt${n === 1 ? '' : 's'} so far`
}

/** Status of a diagnosis session in the history table, with how many attempts it has taken. */
export function SessionBadge({ session }: { session: SessionOut }) {
  const style = STYLES[session.status]
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1" data-testid="session-badge" data-status={session.status}>
      <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${style.className}`}>
        {style.label}
      </span>
      <span className="text-xs text-slate-500" data-testid="session-attempts">
        {attemptsText(session)}
      </span>
    </p>
  )
}

/** The attempts of a session, in order, with whether each one worked. */
export function AttemptsTimeline({ session }: { session: SessionOut }) {
  return (
    <div data-testid="attempts-timeline">
      <h4 className="text-xs font-semibold uppercase text-slate-500">Solution attempts ({session.attempt_count})</h4>
      <ol className="mt-1.5 space-y-2">
        {session.attempts.map((a) => (
          <li key={a.attempt_number} className="rounded-lg border border-slate-200 bg-white p-3" data-testid="attempt-row">
            <p className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Attempt {a.attempt_number}
              <Outcome helpful={a.was_helpful} />
            </p>
            <p className="mt-1 text-slate-800">
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
    </div>
  )
}

function Outcome({ helpful }: { helpful: boolean | null }) {
  if (helpful === true) {
    return <span className="rounded bg-emerald-100 px-1.5 py-0.5 normal-case text-emerald-800">Solved it</span>
  }
  if (helpful === false) {
    return <span className="rounded bg-slate-200 px-1.5 py-0.5 normal-case text-slate-600">Did not work</span>
  }
  return <span className="rounded bg-sky-100 px-1.5 py-0.5 normal-case text-sky-800">Awaiting an answer</span>
}
