import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { getStats } from '../api/client'
import { ErrorBanner } from '../components/ErrorBanner'
import { InboxIcon, RefreshIcon } from '../components/icons'
import { toPercent } from '../lib/format'
import type { StatsResponse } from '../types/api'

/** The outcome of one fetch, tagged with the refresh it answers (so "loading" can be derived, not stored). */
interface Outcome {
  key: number
  data?: StatsResponse
  error?: unknown
}

const NO_VALUE = '—'

const formatPct = (value: number | null) => (value === null ? NO_VALUE : `${value}%`)
const formatScore = (value: number | null) => (value === null ? NO_VALUE : `${toPercent(value)}%`)

export function StatsPage() {
  const [reloadKey, setReloadKey] = useState(0)
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getStats(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setOutcome({ key: reloadKey, data })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setOutcome({ key: reloadKey, error })
      })
    return () => controller.abort()
  }, [reloadKey])

  const loading = outcome?.key !== reloadKey
  const stats = !loading ? outcome?.data : undefined
  const error = !loading ? outcome?.error : undefined

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-navy-900">Statistics</h2>
          <p className="text-sm text-slate-600">
            How the system is being used, and how its knowledge base is growing from technician reviews.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setReloadKey((k) => k + 1)}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:opacity-60"
        >
          <RefreshIcon className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {error !== undefined && <ErrorBanner error={error} onRetry={() => setReloadKey((k) => k + 1)} />}
      {loading && <StatsSkeleton />}
      {stats && <StatsDashboard stats={stats} />}
    </div>
  )
}

function StatsDashboard({ stats }: { stats: StatsResponse }) {
  const { resolution, review, average_confidence: confidence } = stats
  const sessions = stats.sessions // absent on a backend that predates sessions
  const kbAvailable = stats.knowledge_base_size !== null

  return (
    <div className="space-y-5" data-testid="stats-dashboard">
      {stats.total_diagnoses_performed === 0 && (
        <div className="flex items-center gap-3 rounded-xl border-2 border-dashed border-slate-300 bg-white/60 px-5 py-4 text-slate-600" data-testid="stats-empty">
          <InboxIcon className="h-8 w-8 shrink-0 text-slate-400" />
          <p className="text-sm">
            No diagnoses yet, so there is nothing to average.{' '}
            <Link to="/" className="font-medium text-accent-700 hover:underline">
              Diagnose an issue
            </Link>{' '}
            and these numbers will fill in.
          </p>
        </div>
      )}

      {/* ---- Headline cards ---- */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Diagnoses performed"
          value={String(stats.total_diagnoses_performed)}
          hint={`${stats.text_diagnoses} text · ${stats.image_diagnoses} photo`}
          testId="stat-total"
        />
        <StatCard
          label="Resolved from similar cases"
          value={formatPct(resolution.similar_cases_pct)}
          hint={
            resolution.counted === 0
              ? 'No text diagnoses yet'
              : `${resolution.similar_cases} of ${resolution.counted} text diagnoses`
          }
          testId="stat-similar"
        />
        <StatCard
          label="Knowledge base records"
          value={kbAvailable ? String(stats.knowledge_base_size) : NO_VALUE}
          hint={
            kbAvailable
              ? `${stats.original_seed_count} seed · ${stats.verified_fix_count ?? stats.technician_verified_count} verified · ${stats.provisional_fix_count ?? 0} provisional · ${stats.failed_fix_count ?? 0} failed`
              : 'Unavailable right now'
          }
          testId="stat-kb"
        />
        <StatCard
          label="Verified by technicians"
          value={kbAvailable ? String(stats.technician_verified_count) : NO_VALUE}
          hint={`${review.confirmed} confirmed · ${review.corrected} corrected`}
          accent
          testId="stat-verified"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* ---- How diagnoses were resolved ---- */}
        <Panel title="How diagnoses were resolved" subtitle="Text diagnoses, by what the answer was based on." testId="panel-resolution">
          {resolution.counted === 0 ? (
            <p className="text-sm text-slate-500">Nothing to show yet.</p>
          ) : (
            <>
              <SplitBar
                parts={[
                  { label: 'Similar past cases', value: resolution.similar_cases, className: 'bg-accent-500' },
                  { label: 'General reasoning', value: resolution.general_reasoning, className: 'bg-slate-400' },
                ]}
                ariaLabel={`${resolution.similar_cases} resolved from similar cases and ${resolution.general_reasoning} from general reasoning`}
              />
              <dl className="mt-3 space-y-1.5 text-sm">
                <Row label="Similar past cases" dotClass="bg-accent-500" value={`${formatPct(resolution.similar_cases_pct)} (${resolution.similar_cases})`} testId="pct-similar" />
                <Row label="General reasoning" dotClass="bg-slate-400" value={`${formatPct(resolution.general_reasoning_pct)} (${resolution.general_reasoning})`} testId="pct-general" />
              </dl>
            </>
          )}
        </Panel>

        {/* ---- Knowledge base growth ---- */}
        <Panel title="Knowledge base" subtitle="Original records, fixes confirmed to work, and fixes reported not to." testId="panel-kb">
          {!kbAvailable ? (
            <p className="text-sm text-slate-500">The knowledge base could not be read right now. Usage numbers are still shown.</p>
          ) : (
            <>
              <SplitBar
                parts={[
                  { label: 'Original seed', value: stats.original_seed_count ?? 0, className: 'bg-slate-400' },
                  { label: 'Verified fixes', value: stats.verified_fix_count ?? stats.technician_verified_count ?? 0, className: 'bg-accent-500' },
                  { label: 'Provisional fixes', value: stats.provisional_fix_count ?? 0, className: 'bg-sky-300' },
                  { label: 'Failed fixes', value: stats.failed_fix_count ?? 0, className: 'bg-amber-400' },
                ]}
                ariaLabel={`${stats.original_seed_count} seed records, ${stats.verified_fix_count ?? stats.technician_verified_count} verified fixes, ${stats.provisional_fix_count ?? 0} provisional fixes and ${stats.failed_fix_count ?? 0} failed fixes`}
              />
              <dl className="mt-3 space-y-1.5 text-sm">
                <Row label="Original seed" dotClass="bg-slate-400" value={String(stats.original_seed_count)} testId="kb-seed-count" />
                <Row label="Verified fixes" dotClass="bg-accent-500" value={String(stats.verified_fix_count ?? stats.technician_verified_count)} testId="kb-verified-count" />
                <Row label="Provisional (confirmed once)" dotClass="bg-sky-300" value={String(stats.provisional_fix_count ?? 0)} testId="kb-provisional-count" />
                <Row label="Failed fixes (did not work)" dotClass="bg-amber-400" value={String(stats.failed_fix_count ?? 0)} testId="kb-failed-count" />
              </dl>
            </>
          )}
        </Panel>

        {/* ---- Confidence ---- */}
        <Panel title="Average confidence" subtitle="Two separate signals, so a high one does not hide a low one." testId="panel-confidence">
          <div className="space-y-3">
            <MeterRow label="Retrieval similarity" note="How closely past cases matched" value={confidence.retrieval} testId="avg-retrieval" />
            <MeterRow label="AI self-reported" note="How sure the model said it was" value={confidence.llm} testId="avg-llm" />
            <MeterRow label="Photo assessments" note="Vision model's own certainty" value={confidence.image} testId="avg-image" />
          </div>
        </Panel>

        {/* ---- Diagnosis sessions ---- */}
        {sessions && (
          <Panel title="Diagnosis sessions" subtitle="Problems worked through one solution at a time." testId="panel-sessions">
            {sessions.total === 0 ? (
              <p className="text-sm text-slate-500">No sessions yet.</p>
            ) : (
              <>
                <SplitBar
                  parts={[
                    { label: 'Resolved', value: sessions.resolved, className: 'bg-emerald-500' },
                    { label: 'In progress', value: sessions.in_progress, className: 'bg-sky-400' },
                    { label: 'Needs a human', value: sessions.abandoned, className: 'bg-amber-400' },
                  ]}
                  ariaLabel={`${sessions.resolved} resolved, ${sessions.in_progress} in progress and ${sessions.abandoned} escalated sessions`}
                />
                <dl className="mt-3 space-y-1.5 text-sm">
                  <Row label="Resolved" dotClass="bg-emerald-500" value={String(sessions.resolved)} testId="sessions-resolved" />
                  <Row label="In progress" dotClass="bg-sky-400" value={String(sessions.in_progress)} testId="sessions-in-progress" />
                  <Row label="Needs a human technician" dotClass="bg-amber-400" value={String(sessions.abandoned)} testId="sessions-abandoned" />
                  <Row
                    label="Average attempts to resolve"
                    dotClass="bg-slate-300"
                    value={sessions.average_attempts_to_resolve === null ? NO_VALUE : String(sessions.average_attempts_to_resolve)}
                    testId="sessions-avg-attempts"
                  />
                </dl>
              </>
            )}
          </Panel>
        )}

        {/* ---- Review progress ---- */}
        <Panel title="Review progress" subtitle="Tickets a technician has checked." testId="panel-review">
          <dl className="space-y-1.5 text-sm">
            <Row label="Waiting for review" dotClass="bg-amber-400" value={String(review.pending)} testId="review-pending" />
            <Row label="Confirmed" dotClass="bg-emerald-500" value={String(review.confirmed)} testId="review-confirmed" />
            <Row label="Corrected" dotClass="bg-accent-500" value={String(review.corrected)} testId="review-corrected" />
          </dl>
          {review.pending > 0 && (
            <Link to="/history?status=pending" className="mt-3 inline-flex text-sm font-medium text-accent-700 hover:underline">
              Review pending tickets →
            </Link>
          )}
        </Panel>
      </div>
    </div>
  )
}

function StatCard({ label, value, hint, accent = false, testId }: { label: string; value: string; hint: string; accent?: boolean; testId: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" data-testid={testId}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1.5 text-3xl font-semibold tabular-nums ${accent ? 'text-accent-700' : 'text-navy-900'}`} data-testid={`${testId}-value`}>
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  )
}

function Panel({ title, subtitle, testId, children }: { title: string; subtitle: string; testId: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" data-testid={testId}>
      <h3 className="text-sm font-semibold text-navy-900">{title}</h3>
      <p className="mb-3 text-xs text-slate-500">{subtitle}</p>
      {children}
    </section>
  )
}

function Row({ label, value, dotClass, testId }: { label: string; value: string; dotClass: string; testId: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="flex items-center gap-2 text-slate-600">
        <span className={`h-2.5 w-2.5 rounded-full ${dotClass}`} aria-hidden="true" />
        {label}
      </dt>
      <dd className="font-semibold tabular-nums text-slate-800" data-testid={testId}>
        {value}
      </dd>
    </div>
  )
}

function SplitBar({ parts, ariaLabel }: { parts: { label: string; value: number; className: string }[]; ariaLabel: string }) {
  const total = parts.reduce((sum, part) => sum + part.value, 0)
  return (
    <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-200" role="img" aria-label={ariaLabel}>
      {total > 0 &&
        parts.map((part) => (
          <div key={part.label} className={`h-full transition-[width] duration-500 ${part.className}`} style={{ width: `${(part.value / total) * 100}%` }} />
        ))}
    </div>
  )
}

function MeterRow({ label, note, value, testId }: { label: string; note: string; value: number | null; testId: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-slate-700">
          {label} <span className="text-xs font-normal text-slate-500">· {note}</span>
        </p>
        <p className="text-sm font-semibold tabular-nums text-slate-800" data-testid={testId}>
          {formatScore(value)}
        </p>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200" role="img" aria-label={`${label}: ${formatScore(value)}`}>
        <div className="h-full rounded-full bg-accent-500 transition-[width] duration-500" style={{ width: value === null ? '0%' : `${toPercent(value)}%` }} />
      </div>
    </div>
  )
}

function StatsSkeleton() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Loading statistics" data-testid="stats-loading">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-[104px] animate-pulse rounded-xl border border-slate-200 bg-white" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-36 animate-pulse rounded-xl border border-slate-200 bg-white" />
        ))}
      </div>
    </div>
  )
}
