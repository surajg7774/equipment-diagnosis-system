import { Fragment, useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getHistory, getKnowledgeBaseStats } from '../api/client'
import { CorrectionForm } from '../components/CorrectionForm'
import { ErrorBanner } from '../components/ErrorBanner'
import { KnowledgeBaseBar } from '../components/KnowledgeBaseBar'
import { Pagination } from '../components/Pagination'
import { ReviewActions } from '../components/ReviewActions'
import { ReviewBadge } from '../components/ReviewBadge'
import { AttemptsTimeline, SessionBadge } from '../components/SessionBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { InboxIcon, RefreshIcon } from '../components/icons'
import { formatDateTime, toPercent, truncate } from '../lib/format'
import type { HistoryItem, HistoryPage as HistoryPageData, KnowledgeBaseStats, ReviewResponse, ReviewStatus } from '../types/api'

const PAGE_SIZE = 10

const FILTERS: { value: ReviewStatus | null; label: string }[] = [
  { value: null, label: 'All' },
  { value: 'pending', label: 'Needs review' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'corrected', label: 'Corrected' },
]

type Status =
  | { phase: 'loading' }
  | { phase: 'ready'; data: HistoryPageData }
  | { phase: 'error'; error: unknown }

/** The outcome of one fetch, tagged with the request it answers. */
interface Outcome {
  key: string
  data?: HistoryPageData
  error?: unknown
}

/** The review fields a confirm/correct changes: applied locally so the row updates instantly. */
type ReviewPatch = Pick<
  HistoryItem,
  'review_status' | 'review_priority' | 'corrected_root_cause' | 'corrected_fix' | 'reviewed_at' | 'kb_record_id'
>

function parseFilter(value: string | null): ReviewStatus | null {
  return value === 'pending' || value === 'confirmed' || value === 'corrected' ? value : null
}

export function HistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const page = Math.max(1, Number.parseInt(searchParams.get('page') ?? '1', 10) || 1)
  const filter = parseFilter(searchParams.get('status'))

  const [reloadKey, setReloadKey] = useState(0)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [patches, setPatches] = useState<Record<number, ReviewPatch>>({})
  const [kbStats, setKbStats] = useState<KnowledgeBaseStats | null>(null)

  // "Loading" is derived: an outcome only counts if it answers the CURRENT page/filter/refresh request.
  const requestKey = `${page}:${filter ?? 'all'}:${reloadKey}`
  const status: Status =
    outcome?.key !== requestKey
      ? { phase: 'loading' }
      : outcome.data
        ? { phase: 'ready', data: outcome.data }
        : { phase: 'error', error: outcome.error }

  const navigate = useCallback(
    (nextPage: number, nextFilter: ReviewStatus | null) => {
      setExpandedId(null)
      setEditingId(null)
      const params: Record<string, string> = {}
      if (nextFilter) params.status = nextFilter
      if (nextPage > 1) params.page = String(nextPage)
      setSearchParams(params)
    },
    [setSearchParams],
  )

  useEffect(() => {
    const controller = new AbortController()
    const key = `${page}:${filter ?? 'all'}:${reloadKey}`
    getHistory(page, PAGE_SIZE, controller.signal, filter ?? undefined)
      .then((data) => {
        if (controller.signal.aborted) return
        // The requested page no longer exists (e.g. a stale ?page=9): jump to the last real one.
        if (data.items.length === 0 && data.total > 0 && page > 1) return navigate(data.total_pages, filter)
        setOutcome({ key, data })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setOutcome({ key, error })
      })
    return () => controller.abort()
  }, [page, filter, reloadKey, navigate])

  // The knowledge-base counters (a failure just hides the bar; the page works without it).
  useEffect(() => {
    const controller = new AbortController()
    getKnowledgeBaseStats(controller.signal)
      .then(setKbStats)
      .catch(() => undefined)
    return () => controller.abort()
  }, [reloadKey])

  function onReviewed(ticketId: number, response: ReviewResponse) {
    setPatches((current) => ({
      ...current,
      [ticketId]: {
        review_status: response.review_status,
        review_priority: response.review_priority,
        corrected_root_cause: response.corrected_root_cause,
        corrected_fix: response.corrected_fix,
        reviewed_at: response.reviewed_at,
        kb_record_id: response.kb_record_id,
      },
    }))
    setKbStats(response.knowledge_base)
    setEditingId(null)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-navy-900">Ticket history</h2>
          <p className="text-sm text-slate-600">
            Every diagnosed issue, newest first. Confirm a diagnosis that was right, or correct one that was
            wrong: verified cases improve future results.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setReloadKey((k) => k + 1)}
          disabled={status.phase === 'loading'}
          className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:opacity-60"
        >
          <RefreshIcon className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {kbStats && <KnowledgeBaseBar stats={kbStats} />}

      <div role="tablist" aria-label="Filter by review status" className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            role="tab"
            aria-selected={filter === f.value}
            data-testid={`filter-${f.value ?? 'all'}`}
            onClick={() => navigate(1, f.value)}
            className={`rounded-full px-3 py-1 text-sm font-medium ring-1 ring-inset transition-colors ${
              filter === f.value
                ? 'bg-navy-800 text-white ring-navy-800'
                : 'bg-white text-slate-700 ring-slate-300 hover:bg-slate-50'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {status.phase === 'error' && <ErrorBanner error={status.error} onRetry={() => setReloadKey((k) => k + 1)} />}

      {status.phase === 'loading' && <TableSkeleton />}

      {status.phase === 'ready' && status.data.total === 0 && !filter && (
        <div className="rounded-xl border-2 border-dashed border-slate-300 bg-white/60 px-6 py-14 text-center" data-testid="history-empty">
          <InboxIcon className="mx-auto h-10 w-10 text-slate-400" />
          <p className="mt-3 font-medium text-slate-700">No tickets yet — diagnose an issue to get started</p>
          <Link
            to="/"
            className="mt-4 inline-flex rounded-lg bg-accent-600 px-4 py-2 text-sm font-semibold text-white hover:bg-accent-700"
          >
            Diagnose an issue
          </Link>
        </div>
      )}

      {status.phase === 'ready' && status.data.total === 0 && filter && (
        <div className="rounded-xl border-2 border-dashed border-slate-300 bg-white/60 px-6 py-10 text-center text-slate-600" data-testid="history-empty-filtered">
          {filter === 'pending' ? 'Nothing is waiting for review.' : `No ${filter} tickets yet.`}
        </div>
      )}

      {status.phase === 'ready' && status.data.total > 0 && (
        <>
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm" data-testid="history-table">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-3">Ticket</th>
                  <th scope="col" className="px-4 py-3">Severity</th>
                  <th scope="col" className="px-4 py-3">Issue &amp; diagnosis</th>
                  <th scope="col" className="whitespace-nowrap px-4 py-3">Created</th>
                  <th scope="col" className="px-4 py-3">Review</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {status.data.items.map((original) => {
                  const item: HistoryItem = { ...original, ...patches[original.id] }
                  const expanded = expandedId === item.id || editingId === item.id
                  // Photo tickets are stored as "[image upload] <file name>"; the PHOTO chip says that already.
                  const issueText = item.description.replace(/^\[image upload\]\s*/, '')
                  // For a session the row shows the CURRENT (latest) solution, which is the one that worked once resolved.
                  const session = item.session ?? null
                  const latestAttempt = session?.attempts[session.attempts.length - 1]
                  const shownDiagnosis = latestAttempt?.diagnosis ?? item.diagnosis
                  return (
                    <Fragment key={item.id}>
                      <tr className="align-top hover:bg-slate-50/70" data-testid="history-row" data-status={item.review_status}>
                        <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-600">#{item.id}</td>
                        <td className="px-4 py-3">
                          <SeverityBadge severity={item.severity} />
                        </td>
                        <td className="max-w-md px-4 py-3">
                          <p className="text-xs text-slate-500">
                            {item.source === 'image' && (
                              <span className="mr-1.5 rounded bg-slate-100 px-1.5 py-0.5 font-semibold uppercase text-slate-600">photo</span>
                            )}
                            {truncate(issueText, 90)}
                          </p>
                          <p className="mt-0.5 text-slate-800" title={shownDiagnosis}>
                            {truncate(shownDiagnosis, 140)}
                          </p>
                          {session && (
                            <div className="mt-1.5">
                              <SessionBadge session={session} />
                            </div>
                          )}
                          <button
                            type="button"
                            onClick={() => setExpandedId(expanded ? null : item.id)}
                            aria-expanded={expanded}
                            className="mt-1 text-xs font-medium text-accent-700 hover:underline"
                          >
                            {expanded ? 'Hide details' : 'Show details'}
                          </button>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-slate-600">{formatDateTime(item.created_at)}</td>
                        <td className="min-w-48 px-4 py-3">
                          <ReviewBadge status={item.review_status} priority={item.review_priority} />
                          {item.reviewed_at && (
                            <p className="mt-1 text-[11px] text-slate-500">{formatDateTime(item.reviewed_at)}</p>
                          )}
                          <ReviewActions
                            ticketId={item.id}
                            status={item.review_status}
                            onReviewed={(response) => onReviewed(item.id, response)}
                            onCorrect={() => {
                              setEditingId(item.id)
                              setExpandedId(item.id)
                            }}
                          />
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="bg-slate-50" data-testid="history-details">
                          <td />
                          <td colSpan={4} className="space-y-3 px-4 pb-4 text-sm text-slate-700">
                            <div>
                              <h4 className="text-xs font-semibold uppercase text-slate-500">Reported issue</h4>
                              <p className="whitespace-pre-line">{issueText}</p>
                            </div>

                            {session && session.attempts.length > 0 && <AttemptsTimeline session={session} />}

                            <div className="grid gap-3 md:grid-cols-2" data-testid="comparison">
                              <div className="rounded-lg border border-slate-200 bg-white p-3" data-testid="ai-version">
                                <h4 className="text-xs font-semibold uppercase text-slate-500">
                                  AI diagnosis{session && session.attempt_count > 1 ? ' (first attempt)' : ''}
                                </h4>
                                <p className="mt-1 whitespace-pre-line">{item.diagnosis}</p>
                                <h4 className="mt-2 text-xs font-semibold uppercase text-slate-500">AI recommended action</h4>
                                <p className="mt-1 whitespace-pre-line">{item.recommended_action}</p>
                                <p className="mt-2 text-xs text-slate-500">Match confidence {toPercent(item.confidence_score)}%</p>
                              </div>
                              <div
                                className={`rounded-lg border p-3 ${
                                  item.review_status === 'corrected' ? 'border-accent-300 bg-sky-50/60' : 'border-dashed border-slate-300 bg-white'
                                }`}
                                data-testid="technician-version"
                              >
                                <h4 className="text-xs font-semibold uppercase text-slate-500">Technician&apos;s version</h4>
                                {item.review_status === 'corrected' ? (
                                  <>
                                    <p className="mt-1 whitespace-pre-line" data-testid="corrected-root-cause">{item.corrected_root_cause}</p>
                                    <h4 className="mt-2 text-xs font-semibold uppercase text-slate-500">Actual fix</h4>
                                    <p className="mt-1 whitespace-pre-line" data-testid="corrected-fix">{item.corrected_fix}</p>
                                  </>
                                ) : (
                                  <p className="mt-1 text-slate-500">
                                    {item.review_status === 'confirmed'
                                      ? 'Confirmed as correct: the AI diagnosis above is in the knowledge base.'
                                      : 'Not reviewed yet.'}
                                  </p>
                                )}
                              </div>
                            </div>

                            {editingId === item.id && (
                              <CorrectionForm
                                ticketId={item.id}
                                initialRootCause={item.corrected_root_cause ?? item.diagnosis}
                                initialFix={item.corrected_fix ?? item.recommended_action}
                                onSaved={(response) => onReviewed(item.id, response)}
                                onCancel={() => setEditingId(null)}
                              />
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>

          <Pagination
            page={status.data.page}
            totalPages={status.data.total_pages}
            total={status.data.total}
            pageSize={status.data.page_size}
            onChange={(next) => navigate(next, filter)}
          />
        </>
      )}
    </div>
  )
}

function TableSkeleton() {
  return (
    <div className="animate-pulse space-y-px overflow-hidden rounded-xl border border-slate-200 bg-white" aria-busy="true" data-testid="history-skeleton">
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-4">
          <div className="h-3 w-10 rounded bg-slate-200" />
          <div className="h-5 w-16 rounded-full bg-slate-200" />
          <div className="h-3 flex-1 rounded bg-slate-100" />
          <div className="h-3 w-24 rounded bg-slate-200" />
        </div>
      ))}
    </div>
  )
}
