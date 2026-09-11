import { useEffect } from 'react'
import { Activity, ArrowDownCircle, ArrowUpCircle, HardDriveDownload, Users } from 'lucide-react'
import { AppShell } from '@/components/layout/AppShell'
import { MetricCard } from '@/components/dashboard/MetricCard'
import { LiveUsageChart } from '@/components/dashboard/LiveUsageChart'
import { HealthPanel } from '@/components/dashboard/HealthPanel'
import { useMonitorStore } from '@/store/useMonitorStore'

function toGigabytes(bytes: number) {
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export default function DashboardPage() {
  const overview = useMonitorStore((state) => state.overview)
  const liveSamples = useMonitorStore((state) => state.liveSamples)
  const statusMessage = useMonitorStore((state) => state.statusMessage)
  const busy = useMonitorStore((state) => state.busy)
  const refreshOverview = useMonitorStore((state) => state.refreshOverview)
  const refreshDevices = useMonitorStore((state) => state.refreshDevices)

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshOverview()
      void refreshDevices()
    }, 5000)

    return () => window.clearInterval(timer)
  }, [refreshDevices, refreshOverview])

  const sample = overview?.latestSample

  return (
    <AppShell
      title="Network Telemetry"
      subtitle="Live OpenWrt bandwidth, storage, and device visibility in a single command-center dashboard."
      status={busy ? 'Refreshing monitor state...' : statusMessage}
    >
      <div className="grid gap-4 lg:grid-cols-4">
        <MetricCard
          label="Download"
          value={`${sample?.downloadMbps ?? 0} Mbps`}
          detail="Current inbound bandwidth over the selected WAN interface."
          accent="cyan"
          icon={ArrowDownCircle}
        />
        <MetricCard
          label="Upload"
          value={`${sample?.uploadMbps ?? 0} Mbps`}
          detail="Current outbound bandwidth currently used on the router."
          accent="emerald"
          icon={ArrowUpCircle}
        />
        <MetricCard
          label="Data Seen"
          value={toGigabytes(sample?.totalDownloadBytes ?? 0)}
          detail="Cumulative received data sampled from the router counters."
          accent="violet"
          icon={HardDriveDownload}
        />
        <MetricCard
          label="Connected"
          value={String(overview?.importantStats.activeDeviceCount ?? 0)}
          detail="Currently discovered clients on your LAN bridge."
          accent="amber"
          icon={Users}
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <LiveUsageChart samples={liveSamples} title="Realtime download and upload stream" />
        <HealthPanel overview={overview} />
      </div>

      <div className="mt-6 rounded-[28px] border border-white/10 bg-black/30 p-6 text-sm text-slate-300 backdrop-blur">
        <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.3em] text-cyan-200">
          <Activity className="h-4 w-4" />
          Operational note
        </div>
        <p>
          The backend writes sampled usage history, nickname mappings, and device policies into local JSON files so the
          dashboard can recover state between restarts.
        </p>
      </div>
    </AppShell>
  )
}
