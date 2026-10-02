import { describeError } from '../lib/errors'
import { AlertIcon, RefreshIcon } from './icons'

interface Props {
  error: unknown
  /** When provided and the error is retryable, a "Try again" button is shown. */
  onRetry?: () => void
  className?: string
}

export function ErrorBanner({ error, onRetry, className = '' }: Props) {
  const view = describeError(error)
  return (
    <div
      role="alert"
      data-testid="error-banner"
      className={`flex gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-red-900 ${className}`}
    >
      <AlertIcon className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{view.title}</p>
        <p className="mt-0.5 text-sm text-red-800">{view.message}</p>
        {view.requestId && <p className="mt-1 font-mono text-xs text-red-700">Reference: {view.requestId}</p>}
        {onRetry && view.retryable && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-sm font-medium text-red-800 ring-1 ring-inset ring-red-300 hover:bg-red-100"
          >
            <RefreshIcon className="h-4 w-4" />
            Try again
          </button>
        )}
      </div>
    </div>
  )
}
