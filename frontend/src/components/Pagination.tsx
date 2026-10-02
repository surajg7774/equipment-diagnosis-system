interface Props {
  page: number
  totalPages: number
  total: number
  pageSize: number
  onChange: (page: number) => void
  disabled?: boolean
}

export function Pagination({ page, totalPages, total, pageSize, onChange, disabled = false }: Props) {
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)
  const button =
    'rounded-md px-3 py-1.5 text-sm font-medium ring-1 ring-inset ring-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50'

  return (
    <nav className="flex flex-wrap items-center justify-between gap-3" aria-label="Pagination" data-testid="pagination">
      <p className="text-sm text-slate-600">
        Showing <span className="font-medium tabular-nums">{first}</span>–<span className="font-medium tabular-nums">{last}</span> of{' '}
        <span className="font-medium tabular-nums">{total}</span> tickets
      </p>
      <div className="flex items-center gap-2">
        <button type="button" className={button} disabled={disabled || page <= 1} onClick={() => onChange(page - 1)} data-testid="prev-page">
          Previous
        </button>
        <span className="px-1 text-sm text-slate-600" data-testid="page-indicator">
          Page {page} of {Math.max(totalPages, 1)}
        </span>
        <button
          type="button"
          className={button}
          disabled={disabled || page >= totalPages}
          onClick={() => onChange(page + 1)}
          data-testid="next-page"
        >
          Next
        </button>
      </div>
    </nav>
  )
}
