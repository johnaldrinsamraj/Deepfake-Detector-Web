import type { HistoryResponse, OverviewResponse } from '../../../shared/types'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type HistoryOverviewProps = {
  history: HistoryResponse | null
  overview: OverviewResponse | null
  selectedRange: '1h' | '24h' | '7d'
  onRangeChange: (range: '1h' | '24h' | '7d') => void
}

const ranges: Array<'1h' | '24h' | '7d'> = ['1h', '24h', '7d']

export function HistoryOverview({
  history,
  overview,
  selectedRange,
  onRangeChange,
}: HistoryOverviewProps) {
  return (
    <section className="rounded-[28px] border border-white/10 bg-black/30 p-6 backdrop-blur">
      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.3em] text-violet-200">Retention Archive</div>
          <h2 className="mt-2 font-['Orbitron'] text-xl uppercase tracking-[0.14em] text-white">Historical usage</h2>
        </div>

        <div className="flex gap-2">
          {ranges.map((range) => (
            <button
              key={range}
              onClick={() => onRangeChange(range)}
              className={`rounded-full px-4 py-2 text-sm transition ${
                selectedRange === range
                  ? 'bg-violet-300/20 text-violet-100'
                  : 'bg-white/5 text-slate-300 hover:bg-white/10'
              }`}
            >
              {range}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <div className="rounded-2xl border border-white/8 bg-white/[0.035] p-4">
          <div className="text-xs uppercase tracking-[0.24em] text-slate-400">Peak down</div>
          <div className="mt-3 font-['Orbitron'] text-2xl text-white">
            {overview?.importantStats.peakDownloadMbps ?? 0} Mbps
          </div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-white/[0.035] p-4">
          <div className="text-xs uppercase tracking-[0.24em] text-slate-400">Peak up</div>
          <div className="mt-3 font-['Orbitron'] text-2xl text-white">
            {overview?.importantStats.peakUploadMbps ?? 0} Mbps
          </div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-white/[0.035] p-4">
          <div className="text-xs uppercase tracking-[0.24em] text-slate-400">Records retained</div>
          <div className="mt-3 font-['Orbitron'] text-2xl text-white">{history?.samples.length ?? 0}</div>
        </div>
      </div>

      <div className="h-[300px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={history?.samples ?? []}>
            <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
            <XAxis
              dataKey="timestamp"
              tick={{ fill: '#94a3b8', fontSize: 12 }}
              tickFormatter={(value) =>
                new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
              }
              axisLine={false}
              tickLine={false}
            />
            <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{
                background: 'rgba(6, 11, 10, 0.95)',
                border: '1px solid rgba(167, 139, 250, 0.16)',
                borderRadius: 18,
              }}
            />
            <Bar dataKey="downloadMbps" fill="#38bdf8" radius={[6, 6, 0, 0]} />
            <Bar dataKey="uploadMbps" fill="#a78bfa" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}
