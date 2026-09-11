import type { OverviewResponse } from '../../../shared/types'

type HealthPanelProps = {
  overview: OverviewResponse | null
}

function formatDuration(seconds: number) {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${minutes}m`
}

const labels = [
  {
    key: 'WAN status',
    selector: (overview: OverviewResponse) => overview.health.wanStatus,
  },
  {
    key: 'Router uptime',
    selector: (overview: OverviewResponse) => formatDuration(overview.health.uptimeSeconds),
  },
  {
    key: 'Load average',
    selector: (overview: OverviewResponse) => overview.health.loadAverage,
  },
  {
    key: 'Memory',
    selector: (overview: OverviewResponse) =>
      `${overview.health.memoryUsedMb} / ${overview.health.memoryTotalMb} MB`,
  },
  {
    key: 'Samples stored',
    selector: (overview: OverviewResponse) => String(overview.importantStats.totalSamples),
  },
  {
    key: 'History file',
    selector: (overview: OverviewResponse) => `${Math.round(overview.storage.usageHistoryBytes / 1024)} KB`,
  },
]

export function HealthPanel({ overview }: HealthPanelProps) {
  if (!overview) {
    return null
  }

  return (
    <section className="rounded-[28px] border border-white/10 bg-black/30 p-6 backdrop-blur">
      <div className="mb-5 text-[11px] uppercase tracking-[0.3em] text-emerald-200">Health Matrix</div>
      <div className="grid gap-3 md:grid-cols-2">
        {labels.map((item) => (
          <div key={item.key} className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.24em] text-slate-400">{item.key}</div>
            <div className="mt-3 text-lg text-white">{item.selector(overview)}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
