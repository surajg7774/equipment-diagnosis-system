/** Placeholder shown while a diagnosis is being generated (3-7 s normally). */
export function ResultSkeleton({ seconds }: { seconds: number }) {
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-busy="true" data-testid="result-skeleton">
      <div className="animate-pulse space-y-4">
        <div className="flex items-center justify-between">
          <div className="h-5 w-28 rounded bg-slate-200" />
          <div className="h-6 w-20 rounded-full bg-slate-200" />
        </div>
        <div className="h-14 rounded-lg bg-slate-100" />
        <div className="space-y-2">
          <div className="h-3 w-24 rounded bg-slate-200" />
          <div className="h-3 w-full rounded bg-slate-100" />
          <div className="h-3 w-5/6 rounded bg-slate-100" />
        </div>
        <div className="space-y-2">
          <div className="h-3 w-32 rounded bg-slate-200" />
          <div className="h-3 w-full rounded bg-slate-100" />
          <div className="h-3 w-4/6 rounded bg-slate-100" />
        </div>
        <div className="h-2.5 rounded-full bg-slate-200" />
      </div>
      <p className="text-center text-xs text-slate-500" role="status">
        Analyzing your report… {seconds}s
        {seconds >= 15 && ' - the AI model may be loading, which can take longer on the first request.'}
      </p>
    </div>
  )
}
