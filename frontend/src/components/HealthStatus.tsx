import { useCallback, useEffect, useState } from 'react'
import { getHealth } from '../api/client'
import type { HealthResponse } from '../types/api'

type State =
  | { kind: 'checking' }
  | { kind: 'offline' }
  | { kind: 'ok' }
  | { kind: 'degraded'; failing: string[] }

const POLL_MS = 30_000

function failingParts(h: HealthResponse): string[] {
  const parts: [string, string][] = [
    ['database', h.database],
    ['vector store', h.vector_store],
    ['LLM', h.llm],
  ]
  return parts.filter(([, status]) => status !== 'ok').map(([name]) => name)
}

/** Small pill in the header showing whether the backend (and its LLM) is up. */
export function HealthStatus() {
  const [state, setState] = useState<State>({ kind: 'checking' })

  const check = useCallback((signal?: AbortSignal) => {
    getHealth(signal)
      .then((health) =>
        setState(health.status === 'ok' ? { kind: 'ok' } : { kind: 'degraded', failing: failingParts(health) }),
      )
      .catch(() => {
        if (!signal?.aborted) setState({ kind: 'offline' })
      })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    check(controller.signal)
    const timer = setInterval(() => check(controller.signal), POLL_MS)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [check])

  const view = {
    checking: { dot: 'bg-slate-400 animate-pulse', text: 'Checking…' },
    ok: { dot: 'bg-emerald-400', text: 'Backend online' },
    offline: { dot: 'bg-red-400', text: 'Backend offline' },
    degraded: { dot: 'bg-yellow-400', text: state.kind === 'degraded' ? `Degraded: ${state.failing.join(', ')}` : '' },
  }[state.kind]

  return (
    <button
      type="button"
      onClick={() => check()}
      title="Backend status (click to re-check)"
      data-testid="health-status"
      data-state={state.kind}
      className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-inset ring-white/15 hover:bg-white/15"
    >
      <span className={`h-2 w-2 rounded-full ${view.dot}`} aria-hidden="true" />
      {view.text}
    </button>
  )
}
