import { Fragment, useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getHistory } from '../api/client'
import { ErrorBanner } from '../components/ErrorBanner'
import { FeedbackButtons } from '../components/FeedbackButtons'
import { Pagination } from '../components/Pagination'
import { SeverityBadge } from '../components/SeverityBadge'
import { InboxIcon, RefreshIcon } from '../components/icons'
import { formatDateTime, toPercent, truncate } from '../lib/format'
import type { HistoryPage as HistoryPageData } from '../types/api'

const PAGE_SIZE = 10

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

export function HistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const page = Math.max(1, Number.parseInt(searchParams.get('page') ?? '1', 10) || 1)

  const [reloadKey, setReloadKey] = useState(0)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  // "Loading" is derived: an outcome only counts if it answers the CURRENT page/refresh request.
  const requestKey = `${page}:${reloadKey}`
  const status: Status =
    outcome?.key !== requestKey
      ? { phase: 'loading' }
      : outcome.data
        ? { phase: 'ready', data: outcome.data }
        : { phase: 'error', error: outcome.error }

  const goToPage = useCallback(
    (next: number) => {
      setExpandedId(null)
      setSearchParams(next <= 1 ? {} : { page: String(next) })
    },
    [setSearchParams],
  )

  useEffect(() => {
    const controller = new AbortController()
    getHistory(page, PAGE_SIZE, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        // The requested page no longer exists (e.g. a stale ?page=9): jump to the last real one.
        if (data.items.length === 0 && data.total > 0 && page > 1) return goToPage(data.total_pages)
        setOutcome({ key: `${page}:${reloadKey}`, data })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setOutcome({ key: `${page}:${reloadKey}`, error })
      })
    return () => controller.abort()
  }, [page, reloadKey, goToPage])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-navy-900">Ticket history</h2>
          <p className="text-sm text-slate-600">Every diagnosed issue, newest first. Rate a diagnosis to help track accuracy.</p>
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

      {status.phase === 'error' && <ErrorBanner error={status.error} onRetry={() => setReloadKey((k) => k + 1)} />}

      {status.phase === 'loading' && <TableSkeleton />}

      {status.phase === 'ready' && status.data.total === 0 && (
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
                  <th scope="col" className="px-4 py-3">Feedback</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {status.data.items.map((item) => {
                  const expanded = expandedId === item.id
                  // Photo tickets are stored as "[image upload] <file name>"; the PHOTO chip says that already.
                  const issueText = item.description.replace(/^\[image upload\]\s*/, '')
                  return (
                    <Fragment key={item.id}>
                      <tr className="align-top hover:bg-slate-50/70" data-testid="history-row">
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
                          <p className="mt-0.5 text-slate-800" title={item.diagnosis}>
                            {truncate(item.diagnosis, 140)}
                          </p>
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
                        <td className="px-4 py-3">
                          <FeedbackButtons ticketId={item.id} initial={item.feedback_was_correct} />
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="bg-slate-50" data-testid="history-details">
                          <td />
                          <td colSpan={4} className="px-4 pb-4 text-sm text-slate-700">
                            <dl className="space-y-2">
                              <div>
                                <dt className="text-xs font-semibold uppercase text-slate-500">Reported issue</dt>
                                <dd className="whitespace-pre-line">{issueText}</dd>
                              </div>
                              <div>
                                <dt className="text-xs font-semibold uppercase text-slate-500">Diagnosis</dt>
                                <dd className="whitespace-pre-line">{item.diagnosis}</dd>
                              </div>
                              <div>
                                <dt className="text-xs font-semibold uppercase text-slate-500">Recommended action</dt>
                                <dd className="whitespace-pre-line">{item.recommended_action}</dd>
                              </div>
                              <div>
                                <dt className="text-xs font-semibold uppercase text-slate-500">Match confidence</dt>
                                <dd>{toPercent(item.confidence_score)}%</dd>
                              </div>
                            </dl>
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
            onChange={goToPage}
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
