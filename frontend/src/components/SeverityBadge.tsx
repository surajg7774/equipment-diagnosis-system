import type { Severity } from '../types/api'

const STYLES: Record<Severity, { label: string; badge: string; dot: string }> = {
  low: { label: 'Low', badge: 'bg-emerald-100 text-emerald-800 ring-emerald-600/25', dot: 'bg-emerald-500' },
  medium: { label: 'Medium', badge: 'bg-yellow-100 text-yellow-900 ring-yellow-600/30', dot: 'bg-yellow-500' },
  high: { label: 'High', badge: 'bg-red-100 text-red-800 ring-red-600/25', dot: 'bg-red-500' },
}

/** Green / yellow / red pill. Never rendered for input that produced no severity. */
export function SeverityBadge({ severity, className = '' }: { severity: Severity; className?: string }) {
  const s = STYLES[severity]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ring-1 ring-inset ${s.badge} ${className}`}
      data-testid="severity-badge"
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} aria-hidden="true" />
      {s.label}
      <span className="sr-only"> severity</span>
    </span>
  )
}
