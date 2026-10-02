import type { ReactNode } from 'react'
import type { DiagnoseResponse } from '../types/api'
import { BasisBanner } from './BasisBanner'
import { ConfidenceMeters } from './ConfidenceMeters'
import { FeedbackButtons } from './FeedbackButtons'
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

/** Result for a real equipment issue (is_valid_issue = true). */
export function ResultCard({ data }: { data: DiagnoseResponse }) {
  const grounded = data.diagnosis_basis === 'similar_cases'

  return (
    <div className="space-y-5" data-testid="valid-result">
      <section className="space-y-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-label="Diagnosis">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-navy-900">Diagnosis</h2>
          <div className="flex items-center gap-2">
            {data.ticket_id !== null && (
              <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600" data-testid="ticket-id">
                Ticket #{data.ticket_id}
              </span>
            )}
            {data.severity !== null && <SeverityBadge severity={data.severity} />}
          </div>
        </div>

        <BasisBanner basis={data.diagnosis_basis} note={data.note} caseCount={data.similar_cases.length} />

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

        {data.ticket_id !== null && (
          <div className="border-t border-slate-100 pt-4">
            <FeedbackButtons ticketId={data.ticket_id} initial={null} withLabel />
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
