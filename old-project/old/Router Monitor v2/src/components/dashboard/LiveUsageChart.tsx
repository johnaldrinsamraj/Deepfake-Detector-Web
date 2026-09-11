import type { LiveUsageSample } from '../../../shared/types'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type LiveUsageChartProps = {
  samples: LiveUsageSample[]
  title: string
}

function formatAxisTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function LiveUsageChart({ samples, title }: LiveUsageChartProps) {
  return (
    <section className="rounded-[28px] border border-white/10 bg-black/30 p-6 backdrop-blur">
      <div className="mb-5 flex items-center justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.3em] text-cyan-200">Traffic Graph</div>
          <h2 className="mt-2 font-['Orbitron'] text-xl uppercase tracking-[0.14em] text-white">{title}</h2>
        </div>
        <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
          {samples.length} samples
        </div>
      </div>

      <div className="h-[320px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={samples}>
            <defs>
              <linearGradient id="downloadGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.6} />
                <stop offset="100%" stopColor="#22d3ee" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="uploadGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#34d399" stopOpacity={0.55} />
                <stop offset="100%" stopColor="#34d399" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatAxisTime}
              tick={{ fill: '#94a3b8', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: '#94a3b8', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              width={40}
              tickFormatter={(value) => `${value}`}
            />
            <Tooltip
              contentStyle={{
                background: 'rgba(6, 11, 10, 0.95)',
                border: '1px solid rgba(125, 211, 252, 0.16)',
                borderRadius: 18,
              }}
              labelFormatter={(value) => formatAxisTime(String(value))}
            />
            <Area
              type="monotone"
              dataKey="downloadMbps"
              stroke="#22d3ee"
              fill="url(#downloadGradient)"
              strokeWidth={2.5}
            />
            <Area
              type="monotone"
              dataKey="uploadMbps"
              stroke="#34d399"
              fill="url(#uploadGradient)"
              strokeWidth={2.5}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}
