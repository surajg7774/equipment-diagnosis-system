import { toPercent } from '../lib/format'
import type { SimilarCase } from '../types/api'

export function SimilarCaseCard({ item }: { item: SimilarCase }) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm" data-testid="similar-case">
      <div className="flex items-center justify-between gap-2">
        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-slate-600">
          {item.equipment_type}
        </span>
        <span className="text-xs text-slate-500">
          <span className="font-semibold tabular-nums text-slate-800">{toPercent(item.similarity_score)}%</span> similar
        </span>
      </div>
      <p className="mt-2 text-sm text-slate-800">{item.issue_description}</p>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer select-none text-xs font-medium text-accent-700 hover:underline">
          Root cause &amp; fix from this case
        </summary>
        <dl className="mt-2 space-y-1.5 border-l-2 border-slate-200 pl-3 text-slate-700">
          <div>
            <dt className="text-xs font-semibold uppercase text-slate-500">Root cause</dt>
            <dd>{item.root_cause}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase text-slate-500">Fix</dt>
            <dd>{item.recommended_fix}</dd>
          </div>
        </dl>
      </details>
    </li>
  )
}
