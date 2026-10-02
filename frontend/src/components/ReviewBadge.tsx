import type { ReviewPriority, ReviewStatus } from '../types/api'
import { CheckCircleIcon, PencilIcon } from './icons'

/**
 * Where a ticket is in the verification workflow. Deliberately NOT green/yellow/red (those are
 * reserved for severity): pending is neutral slate, confirmed is the accent blue, corrected navy.
 */
export function ReviewBadge({ status, priority }: { status: ReviewStatus; priority: ReviewPriority }) {
  if (status === 'confirmed') {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-900 ring-1 ring-inset ring-accent-500/40"
        data-testid="review-badge"
        data-status="confirmed"
      >
        <CheckCircleIcon className="h-3.5 w-3.5" />
        Confirmed
      </span>
    )
  }
  if (status === 'corrected') {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-navy-800 px-2 py-0.5 text-xs font-semibold text-white"
        data-testid="review-badge"
        data-status="corrected"
      >
        <PencilIcon className="h-3 w-3" />
        Corrected
      </span>
    )
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5" data-testid="review-badge" data-status="pending" data-priority={priority}>
      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700 ring-1 ring-inset ring-slate-300">
        Pending review
      </span>
      {priority === 'high' && (
        <span
          className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-900 ring-1 ring-inset ring-amber-400/60"
          title="Medium or high severity: review these first"
          data-testid="review-priority-chip"
        >
          Review first
        </span>
      )}
    </span>
  )
}
