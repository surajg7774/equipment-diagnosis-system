import type { ReactNode } from 'react'
import type { DiagnoseResponse } from '../types/api'
import { BasisBanner } from './BasisBanner'
import { ConfidenceMeters } from './ConfidenceMeters'
import { FeedbackButtons } from './FeedbackButtons'
import { PhotoFindings, PhotoNotUsedNotice } from './PhotoFindings'
import { SeverityBadge } from './SeverityBadge'
import { SimilarCaseCard } from './SimilarCaseCard'
import { InfoIcon } from './icons'

function Block({ title, children, accent = false }: { title: string; children: ReactNode; accent?: boolean }) {
  return (
    <div className={accent ? 'border-l-4 border-accent-500 pl-4' : ''}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <p className="mt-1 whitespace-pre-line text-[15px] leading-relaxed text-slate-800">{children}</p>
    </div>
  )
}

/**
 * Result for a real equipment issue (is_valid_issue = true).
 * `footer` is the "Did this solve it?" area (or the resolved / escalated state) supplied by SessionFlow.
 */
export function ResultCard({ data, footer }: { data: DiagnoseResponse; footer?: ReactNode }) {
  const grounded = data.diagnosis_basis === 'similar_cases'
  const attempt = data.attempt_number ?? null
  // The thumbs rate the ticket's own diagnosis, which is the FIRST attempt. A later attempt in a session
  // has its own "Did this solve it?" question instead, so the thumbs are not shown for it.
  const showThumbs = data.ticket_id !== null && (attempt === null || attempt === 1)
  const failedCases = data.similar_failed_cases ?? []

  return (
    <div className="space-y-5" data-testid="valid-result">
      <section className="space-y-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-label="Diagnosis">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-navy-900">
            {attempt !== null && attempt > 1 ? 'Another possible solution' : 'Diagnosis'}
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            {attempt !== null && data.max_attempts && (
              <span
                className="rounded-md bg-navy-900 px-2 py-0.5 text-xs font-semibold text-white"
                data-testid="attempt-badge"
              >
                Attempt {attempt} of {data.max_attempts}
              </span>
            )}
            {data.ticket_id !== null && (
              <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600" data-testid="ticket-id">
                Ticket #{data.ticket_id}
              </span>
            )}
            {data.severity !== null && <SeverityBadge severity={data.severity} />}
          </div>
        </div>

        <BasisBanner basis={data.diagnosis_basis} note={data.note} caseCount={data.similar_cases.length} />

        {/* A photo was part of this diagnosis: say so, and keep what the AI saw in it visible. */}
        {data.input_sources?.includes('image') && data.image_analysis && <PhotoFindings findings={data.image_analysis} />}
        {/* A photo was attached but could not be used: never let it look as if it counted. */}
        {data.image_note && <PhotoNotUsedNotice note={data.image_note} />}

        {failedCases.length > 0 && (
          <div
            className="flex gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3.5 text-amber-950"
            data-testid="failed-cases-notice"
          >
            <InfoIcon className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div className="min-w-0">
              <p className="text-sm font-semibold">
                A similar problem was reported before where {failedCases.length === 1 ? 'this approach' : 'these approaches'} did not work
              </p>
              <p className="mt-0.5 text-sm text-amber-900/90">The assistant was told to avoid repeating it and to suggest something else.</p>
              <details className="mt-1.5 text-sm">
                <summary className="cursor-pointer select-none text-xs font-medium text-amber-900 hover:underline">
                  What did not work
                </summary>
                <ul className="mt-1.5 space-y-2 border-l-2 border-amber-300 pl-3">
                  {failedCases.map((c) => (
                    <li key={c.id} data-testid="failed-case">
                      <p className="text-amber-950">
                        <span className="font-medium">Diagnosis: </span>
                        {c.root_cause}
                      </p>
                      <p className="whitespace-pre-line text-amber-900/90">
                        <span className="font-medium">Fix: </span>
                        {c.recommended_fix}
                      </p>
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          </div>
        )}

        <Block title="Likely root cause">{data.diagnosis}</Block>
        <Block title="Recommended action" accent>
          {data.recommended_action}
        </Block>

        {/* `??` / typeof guards: tolerate a backend that predates the two new fields (deploy skew). */}
        <ConfidenceMeters
          retrieval={data.retrieval_confidence ?? data.confidence_score}
          ai={typeof data.llm_confidence === 'number' ? data.llm_confidence : null}
          aiDefaulted={data.llm_confidence_defaulted === true}
          grounded={grounded}
        />

        {(showThumbs || footer) && (
          <div className="space-y-4 border-t border-slate-100 pt-4">
            {showThumbs && <FeedbackButtons ticketId={data.ticket_id!} initial={null} withLabel />}
            {footer}
          </div>
        )}
      </section>

      {data.similar_cases.length > 0 && (
        <section aria-label="Similar past cases" data-testid="similar-cases">
          <h3 className="text-sm font-semibold text-slate-700">
            {grounded ? 'Similar past cases used as context' : 'Closest cases found (weak matches, not used by the AI)'}
          </h3>
          <ul className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.similar_cases.map((c) => (
              <SimilarCaseCard key={c.id} item={c} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

/**
 * Result for input that is not an equipment problem (is_valid_issue = false).
 * Deliberately neutral: no severity badge, no ticket id, no confidence, no cases.
 */
export function InvalidResultCard({ data }: { data: DiagnoseResponse }) {
  return (
    <section
      className="space-y-4 rounded-xl border border-slate-300 bg-slate-50 p-5"
      aria-label="Not an equipment issue"
      data-testid="invalid-result"
    >
      <div className="flex items-start gap-3">
        <InfoIcon className="mt-0.5 h-6 w-6 shrink-0 text-slate-500" />
        <div>
          <h2 className="text-lg font-semibold text-slate-800">This doesn&apos;t look like an equipment issue</h2>
          <p className="mt-0.5 text-sm text-slate-600">
            The system couldn&apos;t treat this as a fault to diagnose. Nothing was recorded.
          </p>
        </div>
      </div>

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">What the assistant said</h3>
        <p className="mt-1 whitespace-pre-line text-[15px] leading-relaxed text-slate-700">{data.diagnosis}</p>
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Suggested next step</h3>
        <p className="mt-1 whitespace-pre-line text-[15px] leading-relaxed text-slate-700">{data.recommended_action}</p>
      </div>

      <div
        className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700"
        data-testid="no-ticket-notice"
      >
        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-slate-700">
          No ticket created
        </span>
        <span>{data.note ?? 'This input was not saved to ticket history.'}</span>
      </div>
    </section>
  )
}
