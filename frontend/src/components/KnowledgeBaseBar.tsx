import type { KnowledgeBaseStats } from '../types/api'
import { DatabaseIcon } from './icons'

/** Makes the knowledge base's growth visible: shipped seed records vs technician-verified ones. */
export function KnowledgeBaseBar({ stats }: { stats: KnowledgeBaseStats }) {
  const verifiedShare = stats.total === 0 ? 0 : (stats.verified / stats.total) * 100

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="kb-stats">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-navy-900">
          <DatabaseIcon className="h-5 w-5 text-accent-600" />
          Knowledge base
          <span className="tabular-nums" data-testid="kb-total">
            {stats.total} records
          </span>
        </div>
        <dl className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          <div className="flex items-baseline gap-1.5">
            <dt className="text-slate-500">Seed</dt>
            <dd className="font-semibold tabular-nums text-slate-800" data-testid="kb-seed">
              {stats.seed}
            </dd>
          </div>
          <div className="flex items-baseline gap-1.5">
            <dt className="text-slate-500">Verified by technicians</dt>
            <dd className="font-semibold tabular-nums text-accent-700" data-testid="kb-verified">
              {stats.verified}
            </dd>
            <dd className="text-xs text-slate-500">
              ({stats.verified_confirmed} confirmed · {stats.verified_corrected} corrected)
            </dd>
          </div>
        </dl>
      </div>
      <div
        className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-slate-200"
        role="img"
        aria-label={`${stats.seed} seed records and ${stats.verified} verified records`}
      >
        <div className="h-full bg-slate-400" style={{ width: `${100 - verifiedShare}%` }} />
        <div className="h-full bg-accent-500 transition-[width] duration-500" style={{ width: `${verifiedShare}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-slate-500">
        Confirming or correcting a diagnosis below adds it here, so similar future reports can find it.
      </p>
    </div>
  )
}
