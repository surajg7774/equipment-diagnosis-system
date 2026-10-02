import type { ReactNode } from 'react'
import { toPercent } from '../lib/format'
import { InfoIcon, LinkIcon, SparkIcon } from './icons'

/** Small "i" that reveals an explanation on hover, keyboard focus or tap. */
function InfoTip({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        className="rounded-full text-slate-400 hover:text-slate-700 focus-visible:text-slate-700"
      >
        <InfoIcon className="h-4 w-4" />
      </button>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none absolute right-0 top-full z-20 mt-1.5 hidden w-64 max-w-[calc(100vw-2rem)]rounded-lg bg-navy-900 p-3 text-xs font-normal normal-case leading-relaxed tracking-normal text-slate-100 shadow-lg group-focus-within:block group-hover:block"
      >
        {children}
      </span>
    </span>
  )
}

interface MeterProps {
  testId: string
  kind: 'match' | 'ai'
  title: string
  subtitle: string
  score: number // 0-1
  verdict: string
  /** Show the value as a placeholder (dashed, muted) rather than as a real reading. */
  estimated?: boolean
  tipId: string
  tipLabel: string
  tip: ReactNode
  icon: ReactNode
}

/** One labelled confidence tile. The two kinds differ in icon, colour and wording on purpose. */
function Meter({ testId, kind, title, subtitle, score, verdict, estimated = false, tipId, tipLabel, tip, icon }: MeterProps) {
  const pct = toPercent(score)
  const style =
    kind === 'match'
      ? { tile: 'border-accent-300 bg-sky-50/70', icon: 'text-accent-600', bar: 'bg-accent-500' }
      : { tile: 'border-slate-300 bg-slate-50', icon: 'text-navy-700', bar: 'bg-navy-700' }

  return (
    <div
      className={`rounded-lg border p-3.5 ${style.tile} ${estimated ? 'border-dashed' : ''}`}
      data-testid={testId}
      data-kind={kind}
      data-estimated={estimated || undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <div className={`flex items-center gap-1.5 text-sm font-semibold text-slate-800 ${style.icon}`}>
          {icon}
          <span className="text-slate-800">{title}</span>
        </div>
        <InfoTip id={tipId} label={tipLabel}>
          {tip}
        </InfoTip>
      </div>
      <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>

      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums text-slate-900" data-testid={`${testId}-value`}>
          {pct}%
        </span>
        <span className="text-xs text-slate-600">{verdict}</span>
      </div>
      <div
        className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={title}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${style.bar} ${estimated ? 'opacity-40' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function aiVerdict(score: number): string {
  if (score >= 0.75) return 'fairly sure'
  if (score >= 0.5) return 'moderately sure'
  return 'not very sure'
}

/** One sentence that reads the two scores together, only where they can seem to contradict. */
function interpret(grounded: boolean, ai: number | null): string | null {
  if (ai === null) return null
  if (!grounded && ai >= 0.6) return 'No close past case was found, but the AI is fairly sure of this diagnosis from general knowledge.'
  if (!grounded) return 'No close past case was found and the AI is not very sure either, so treat this as a starting point.'
  if (ai < 0.5) return 'A close past case was found, but the AI is unsure how well it applies to your report.'
  return null
}

interface Props {
  /** Retrieval similarity of the best past case, 0-1. */
  retrieval: number
  /** The model's own self-reported certainty, 0-1; null if the backend did not send one. */
  ai: number | null
  /** True when a close past case existed (diagnosis_basis === 'similar_cases'). */
  grounded: boolean
  /** True when `ai` is only the backend's default because the model gave no usable number. */
  aiDefaulted?: boolean
}

/**
 * The two confidence readings, side by side and deliberately unlike each other:
 *  - Match confidence: how well the knowledge base covers this issue (retrieval similarity).
 *  - AI confidence:    how sure the model says it is (self-reported, independent of any match).
 */
export function ConfidenceMeters({ retrieval, ai, grounded, aiDefaulted = false }: Props) {
  // A defaulted value is not the AI's opinion, so do not "read" it alongside the match score.
  const reading = aiDefaulted ? null : interpret(grounded, ai)

  return (
    <div className="space-y-2.5" data-testid="confidence-meters">
      <div className={`grid gap-3 ${ai !== null ? 'sm:grid-cols-2' : ''}`}>
        <Meter
          testId="meter-match"
          kind="match"
          title="Match confidence"
          subtitle="How closely your report matches past cases"
          score={retrieval}
          verdict={grounded ? 'close match found' : 'no close match'}
          tipId="tip-match"
          tipLabel="What is match confidence?"
          icon={<LinkIcon className="h-4 w-4" />}
          tip="How similar your report is to the closest case in the knowledge base. It shows how well past cases cover this issue, not whether the diagnosis is right. A low value means nothing similar was found."
        />
        {ai !== null && (
          <Meter
            testId="meter-ai"
            kind="ai"
            title="AI confidence"
            subtitle="How sure the AI says it is"
            score={ai}
            verdict={aiDefaulted ? 'estimate unavailable (default shown)' : aiVerdict(ai)}
            estimated={aiDefaulted}
            tipId="tip-ai"
            tipLabel="What is AI confidence?"
            icon={<SparkIcon className="h-4 w-4" />}
            tip="The AI model's own estimate of how certain it is that its diagnosis is correct, given your description. It does not depend on whether a past case matched. It is self-reported, so use it as a rough guide, not a guarantee."
          />
        )}
      </div>
      {reading && (
        <p className="text-xs text-slate-600" data-testid="confidence-reading">
          {reading}
        </p>
      )}
    </div>
  )
}
