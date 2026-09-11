import { useEffect } from 'react'
import { AppShell } from '@/components/layout/AppShell'
import { HistoryOverview } from '@/components/history/HistoryOverview'
import { SettingsPanel } from '@/components/history/SettingsPanel'
import { useMonitorStore } from '@/store/useMonitorStore'

export default function HistoryPage() {
  const overview = useMonitorStore((state) => state.overview)
  const history = useMonitorStore((state) => state.history)
  const settings = useMonitorStore((state) => state.settings)
  const routerTest = useMonitorStore((state) => state.routerTest)
  const selectedRange = useMonitorStore((state) => state.selectedRange)
  const statusMessage = useMonitorStore((state) => state.statusMessage)
  const refreshHistory = useMonitorStore((state) => state.refreshHistory)
  const refreshOverview = useMonitorStore((state) => state.refreshOverview)
  const refreshSettings = useMonitorStore((state) => state.refreshSettings)
  const saveSettings = useMonitorStore((state) => state.saveSettings)
  const testRouter = useMonitorStore((state) => state.testRouter)

  useEffect(() => {
    void refreshHistory(selectedRange)
    void refreshOverview()
    void refreshSettings()
  }, [refreshHistory, refreshOverview, refreshSettings, selectedRange])

  return (
    <AppShell
      title="History And Setup"
      subtitle="Review stored traffic history, retention stats, and the OpenWrt connection settings used by the polling service."
      status={statusMessage}
    >
      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <HistoryOverview
          history={history}
          overview={overview}
          selectedRange={selectedRange}
          onRangeChange={(range) => void refreshHistory(range)}
        />
        <SettingsPanel settings={settings} routerTest={routerTest} onSave={saveSettings} onTest={testRouter} />
      </div>
    </AppShell>
  )
}
