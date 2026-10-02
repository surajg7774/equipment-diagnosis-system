import { NavLink, Outlet } from 'react-router-dom'
import { HealthStatus } from './HealthStatus'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive ? 'bg-white/15 text-white' : 'text-slate-300 hover:bg-white/10 hover:text-white'
  }`

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-white/10 bg-navy-900 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <div className="leading-tight">
              <h1 className="text-base font-semibold tracking-tight">Equipment Diagnosis System</h1>
              <p className="text-xs text-slate-400">AI-assisted fault diagnosis for field technicians</p>
            </div>
          </div>
          <nav className="flex gap-1" aria-label="Main">
            <NavLink to="/" end className={linkClass}>
              Diagnose
            </NavLink>
            <NavLink to="/history" className={linkClass}>
              History
            </NavLink>
            <NavLink to="/stats" className={linkClass}>
              Stats
            </NavLink>
          </nav>
          <div className="ml-auto">
            <HealthStatus />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 py-4 text-center text-xs text-slate-500">
        Suggestions are AI-generated and advisory only. Verify with a qualified technician before acting.
      </footer>
    </div>
  )
}
