import { NavLink } from 'react-router-dom'
import { Activity, History, Router, Shield } from 'lucide-react'
import type { ReactNode } from 'react'

type AppShellProps = {
  title: string
  subtitle: string
  status: string
  children: ReactNode
}

const navItems = [
  { to: '/', label: 'Overview', icon: Activity },
  { to: '/devices', label: 'Devices', icon: Shield },
  { to: '/history', label: 'History', icon: History },
]

export function AppShell({ title, subtitle, status, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(18,190,154,0.16),_transparent_30%),linear-gradient(180deg,_#091111_0%,_#050807_100%)] text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-7xl flex-col px-6 py-6 lg:px-10">
        <header className="mb-8 flex flex-col gap-6 rounded-[28px] border border-white/10 bg-black/30 px-6 py-6 shadow-[0_0_80px_rgba(6,255,190,0.06)] backdrop-blur lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[11px] uppercase tracking-[0.35em] text-cyan-200">
              <Router className="h-3.5 w-3.5" />
              OpenWrt Monitor Grid
            </div>
            <div>
              <h1 className="font-['Orbitron'] text-3xl uppercase tracking-[0.18em] text-white md:text-4xl">
                {title}
              </h1>
              <p className="mt-2 max-w-3xl text-sm text-slate-300">{subtitle}</p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-[auto_auto]">
            <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3">
              <div className="text-[11px] uppercase tracking-[0.28em] text-emerald-200">Status Feed</div>
              <div className="mt-2 text-sm text-emerald-50">{status}</div>
            </div>
          </div>
        </header>

        <nav className="mb-6 flex flex-wrap gap-3">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm transition ${
                  isActive
                    ? 'border-cyan-300/60 bg-cyan-300/15 text-cyan-100 shadow-[0_0_24px_rgba(125,211,252,0.14)]'
                    : 'border-white/10 bg-white/5 text-slate-300 hover:border-white/20 hover:bg-white/10'
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <main className="flex-1">{children}</main>
      </div>
    </div>
  )
}
