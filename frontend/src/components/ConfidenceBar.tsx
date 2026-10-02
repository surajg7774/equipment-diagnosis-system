import { toPercent } from '../lib/format'

interface Props {
  score: number
  label?: string
  /** Small explanatory line under the bar. */
  caption?: string
}

export function ConfidenceBar({ score, label = 'Match confidence', caption }: Props) {
  const pct = toPercent(score)
  return (
    <div data-testid="confidence">
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="font-semibold tabular-nums text-slate-900">{pct}%</span>
      </div>
      <div
        className="h-2.5 overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div className="h-full rounded-full bg-accent-500 transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
      {caption && <p className="mt-1.5 text-xs text-slate-500">{caption}</p>}
    </div>
  )
}
