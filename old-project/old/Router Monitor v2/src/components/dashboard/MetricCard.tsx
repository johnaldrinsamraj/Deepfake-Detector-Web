import type { LucideIcon } from 'lucide-react'

type MetricCardProps = {
  label: string
  value: string
  accent: 'cyan' | 'emerald' | 'amber' | 'violet'
  detail: string
  icon: LucideIcon
}

const accentStyles = {
  cyan: 'from-cyan-400/25 to-cyan-300/0 border-cyan-300/20 text-cyan-100',
  emerald: 'from-emerald-400/25 to-emerald-300/0 border-emerald-300/20 text-emerald-100',
  amber: 'from-amber-400/25 to-amber-300/0 border-amber-300/0 text-amber-100',
  violet: 'from-violet-400/25 to-violet-300/0 border-violet-300/20 text-violet-100',
}

export function MetricCard({ label, value, detail, icon: Icon, accent }: MetricCardProps) {
  return (
    <div className={`rounded-[24px] border bg-gradient-to-br ${accentStyles[accent]} p-5`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.3em] text-slate-300">{label}</div>
          <div className="mt-3 font-['Orbitron'] text-3xl tracking-[0.08em]">{value}</div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/20 p-3 text-white/80">
          <Icon className="h-5 w-5" />
        </div>
      </div>
      <div className="mt-6 text-sm text-slate-300">{detail}</div>
    </div>
  )
}
