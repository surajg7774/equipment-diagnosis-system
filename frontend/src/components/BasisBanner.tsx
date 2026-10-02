import type { DiagnosisBasis } from '../types/api'
import { BulbIcon, LinkIcon } from './icons'

interface Props {
  basis: DiagnosisBasis
  note: string | null
  caseCount: number
}

/**
 * Makes the grounding of a diagnosis impossible to miss. The two states look
 * clearly different: solid blue "based on past cases" vs dashed amber "general reasoning".
 */
export function BasisBanner({ basis, note, caseCount }: Props) {
  if (basis === 'similar_cases') {
    return (
      <div
        data-testid="basis-banner"
        data-basis="similar_cases"
        className="flex gap-3 rounded-lg border border-accent-300 bg-sky-50 p-3.5 text-sky-950"
      >
        <LinkIcon className="mt-0.5 h-5 w-5 shrink-0 text-accent-600" />
        <div>
          <p className="text-sm font-semibold">Based on similar past cases</p>
          <p className="mt-0.5 text-sm text-sky-900/80">
            {caseCount > 0
              ? `The AI was shown the ${caseCount} closest known case${caseCount === 1 ? '' : 's'} as reference examples, then wrote this diagnosis for your specific report.`
              : 'The AI used closely matching past cases as reference examples.'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div
      data-testid="basis-banner"
      data-basis="general_reasoning"
      className="flex gap-3 rounded-lg border-2 border-dashed border-amber-400 bg-amber-50 p-3.5 text-amber-950"
    >
      <BulbIcon className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
      <div>
        <p className="text-sm font-semibold">Based on general reasoning</p>
        <p className="mt-0.5 text-sm text-amber-900/90">
          {note ?? 'No closely matching past case found - diagnosis based on general reasoning.'}
        </p>
        <p className="mt-1 text-xs text-amber-800/80">
          This is not backed by a known case, so treat it with extra caution.
        </p>
      </div>
    </div>
  )
}
