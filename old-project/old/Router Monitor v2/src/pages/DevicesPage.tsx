import { useEffect } from 'react'
import { AppShell } from '@/components/layout/AppShell'
import { DeviceTable } from '@/components/devices/DeviceTable'
import { useMonitorStore } from '@/store/useMonitorStore'

export default function DevicesPage() {
  const devices = useMonitorStore((state) => state.devices)
  const statusMessage = useMonitorStore((state) => state.statusMessage)
  const refreshDevices = useMonitorStore((state) => state.refreshDevices)
  const refreshOverview = useMonitorStore((state) => state.refreshOverview)
  const saveNickname = useMonitorStore((state) => state.saveNickname)
  const runDeviceAction = useMonitorStore((state) => state.runDeviceAction)

  useEffect(() => {
    void refreshDevices()
    const timer = window.setInterval(() => {
      void refreshDevices()
      void refreshOverview()
    }, 5000)

    return () => window.clearInterval(timer)
  }, [refreshDevices, refreshOverview])

  return (
    <AppShell
      title="Client Control"
      subtitle="Name devices, inspect addresses, disconnect unwanted clients, or apply a ban policy directly from the dashboard."
      status={statusMessage}
    >
      <DeviceTable devices={devices} onSaveNickname={saveNickname} onAction={runDeviceAction} />
    </AppShell>
  )
}
