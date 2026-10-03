import { PHOTO_CAVEAT } from '../lib/photo'
import { toPercent } from '../lib/format'
import type { ImageFindings } from '../types/api'
import { SeverityBadge } from './SeverityBadge'
import { AlertIcon, CheckCircleIcon, ImageIcon, InfoIcon } from './icons'

/**
 * Shown on a diagnosis that used a photo: says so plainly, and keeps the vision model's findings visible as
 * part of the explanation (they were given to the same LLM call that wrote the diagnosis).
 */
export function PhotoFindings({ findings }: { findings: ImageFindings }) {
  return (
    <div className="space-y-3 rounded-lg border border-accent-300 bg-sky-50 p-3.5 text-sky-950" data-testid="photo-findings">
      <div className="flex gap-3">
        <ImageIcon className="mt-0.5 h-5 w-5 shrink-0 text-accent-600" />
        <div>
          <p className="text-sm font-semibold" data-testid="photo-basis">
            Diagnosis based on your description and the photo you attached
          </p>
          <p className="mt-0.5 text-sm text-sky-900/80">
            An AI vision model described the photo, and the diagnosis below weighs that together with your description.
          </p>
        </div>
      </div>

      <div className="rounded-md bg-white/70 p-3 ring-1 ring-inset ring-sky-200">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">What the AI sees in your photo</h4>
          {findings.damage_detected ? (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-900 ring-1 ring-inset ring-amber-400/60"
              data-testid="photo-damage-chip"
              data-damage="true"
            >
              <AlertIcon className="h-3 w-3" />
              Possible damage detected
            </span>
          ) : (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700 ring-1 ring-inset ring-slate-300"
              data-testid="photo-damage-chip"
              data-damage="false"
            >
              <CheckCircleIcon className="h-3 w-3" />
              No visible damage
            </span>
          )}
          <SeverityBadge severity={findings.severity} />
        </div>
        <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-slate-800" data-testid="photo-description">
          {findings.description}
        </p>
        <p className="mt-2 text-xs text-slate-500" data-testid="photo-model">
          Assessed by {findings.model_name} ({findings.provider})
          {findings.confidence !== null && <> · the model&apos;s own confidence {toPercent(findings.confidence)}%</>}
        </p>
        <p className="mt-1 flex items-start gap-1.5 text-xs text-slate-500" data-testid="photo-caveat">
          <InfoIcon className="mt-px h-3.5 w-3.5 shrink-0 text-slate-400" />
          {PHOTO_CAVEAT}
        </p>
      </div>
    </div>
  )
}

/** A photo was attached but could not be used: the diagnosis went ahead on the description alone. */
export function PhotoNotUsedNotice({ note }: { note: string }) {
  return (
    <div className="flex gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3.5 text-amber-950" role="status" data-testid="photo-not-used">
      <InfoIcon className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
      <p className="text-sm">{note}</p>
    </div>
  )
}
