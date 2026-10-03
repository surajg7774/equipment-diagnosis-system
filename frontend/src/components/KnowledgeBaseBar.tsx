import type { KnowledgeBaseStats } from '../types/api'
import { DatabaseIcon } from './icons'

/** Makes the knowledge base's growth visible: shipped seed records vs technician-verified ones. */
export function KnowledgeBaseBar({ stats }: { stats: KnowledgeBaseStats }) {
  const failed = stats.failed ?? 0 // absent on a backend that predates thumbs-down learning
  const verifiedShare = stats.total === 0 ? 0 : (stats.verified / stats.total) * 100
  const failedShare = stats.total === 0 ? 0 : (failed / stats.total) * 100

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
            <dt className="text-slate-500">Confirmed working fixes</dt>
            <dd className="font-semibold tabular-nums text-accent-700" data-testid="kb-verified">
              {stats.verified}
            </dd>
            <dd className="text-xs text-slate-500">
              ({stats.verified_confirmed} confirmed · {stats.verified_corrected} corrected)
            </dd>
          </div>
          {failed > 0 && (
            <div className="flex items-baseline gap-1.5">
              <dt className="text-slate-500">Fixes that did not work</dt>
              <dd className="font-semibold tabular-nums text-amber-700" data-testid="kb-failed">
                {failed}
              </dd>
            </div>
          )}
        </dl>
      </div>
      <div
        className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-slate-200"
        role="img"
        aria-label={`${stats.seed} seed records, ${stats.verified} confirmed working fixes and ${failed} fixes that did not work`}
      >
        <div className="h-full bg-slate-400" style={{ width: `${100 - verifiedShare - failedShare}%` }} />
        <div className="h-full bg-accent-500 transition-[width] duration-500" style={{ width: `${verifiedShare}%` }} />
        <div className="h-full bg-amber-400 transition-[width] duration-500" style={{ width: `${failedShare}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-slate-500">
        Confirming or correcting a diagnosis below (or a thumbs up) adds it here as a working fix; a thumbs down records a
        fix that did not work, so similar future reports avoid repeating it.
      </p>
    </div>
  )
}
