import { create } from 'zustand'
import type {
  DeviceActionPayload,
  DeviceActionResult,
  DeviceNicknamePayload,
  DeviceRecord,
  HistoryResponse,
  LiveUsageSample,
  OverviewResponse,
  RouterSettings,
  RouterTestResult,
} from '../../shared/types'
import { requestJson } from '@/utils/api'

type MonitorState = {
  overview: OverviewResponse | null
  liveSamples: LiveUsageSample[]
  history: HistoryResponse | null
  devices: DeviceRecord[]
  settings: RouterSettings | null
  routerTest: RouterTestResult | null
  selectedRange: '1h' | '24h' | '7d'
  busy: boolean
  statusMessage: string
  bootstrap: () => Promise<void>
  refreshOverview: () => Promise<void>
  refreshDevices: () => Promise<void>
  refreshHistory: (range?: '1h' | '24h' | '7d') => Promise<void>
  refreshSettings: () => Promise<void>
  saveNickname: (payload: DeviceNicknamePayload) => Promise<void>
  runDeviceAction: (action: 'disconnect' | 'ban' | 'unban', payload: DeviceActionPayload) => Promise<void>
  saveSettings: (payload: Partial<RouterSettings>) => Promise<void>
  testRouter: (payload?: Partial<RouterSettings>) => Promise<void>
}

async function loadOverview() {
  return await requestJson<OverviewResponse>('/api/overview')
}

export const useMonitorStore = create<MonitorState>((set, get) => ({
  overview: null,
  liveSamples: [],
  history: null,
  devices: [],
  settings: null,
  routerTest: null,
  selectedRange: '24h',
  busy: false,
  statusMessage: 'Loading router data...',

  bootstrap: async () => {
    set({ busy: true, statusMessage: 'Loading OpenWrt dashboard...' })
    try {
      const [overview, liveSamples, history, devices, settings] = await Promise.all([
        loadOverview(),
        requestJson<LiveUsageSample[]>('/api/usage/live?limit=40'),
        requestJson<HistoryResponse>('/api/usage/history?range=24h'),
        requestJson<DeviceRecord[]>('/api/devices'),
        requestJson<RouterSettings>('/api/settings'),
      ])

      set({
        overview,
        liveSamples,
        history,
        devices,
        settings,
        statusMessage: overview.health.lastPollMessage,
      })
    } finally {
      set({ busy: false })
    }
  },

  refreshOverview: async () => {
    const [overview, liveSamples] = await Promise.all([
      loadOverview(),
      requestJson<LiveUsageSample[]>('/api/usage/live?limit=40'),
    ])

    set({
      overview,
      liveSamples,
      statusMessage: overview.health.lastPollMessage,
    })
  },

  refreshDevices: async () => {
    const devices = await requestJson<DeviceRecord[]>('/api/devices')
    set({ devices })
  },

  refreshHistory: async (range) => {
    const nextRange = range ?? get().selectedRange
    const history = await requestJson<HistoryResponse>(`/api/usage/history?range=${nextRange}`)
    set({
      history,
      selectedRange: nextRange,
    })
  },

  refreshSettings: async () => {
    const settings = await requestJson<RouterSettings>('/api/settings')
    set({ settings })
  },

  saveNickname: async (payload) => {
    set({ busy: true, statusMessage: `Saving nickname for ${payload.ip}...` })
    try {
      await requestJson('/api/devices/nickname', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      await Promise.all([get().refreshDevices(), get().refreshOverview()])
      set({ statusMessage: `Nickname saved for ${payload.ip}.` })
    } finally {
      set({ busy: false })
    }
  },

  runDeviceAction: async (action, payload) => {
    set({ busy: true, statusMessage: `${action} request queued for ${payload.mac}...` })
    try {
      const result = await requestJson<DeviceActionResult>(`/api/devices/${action}`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      await Promise.all([get().refreshDevices(), get().refreshOverview()])
      set({ statusMessage: result.message })
    } finally {
      set({ busy: false })
    }
  },

  saveSettings: async (payload) => {
    set({ busy: true, statusMessage: 'Saving router settings...' })
    try {
      const settings = await requestJson<RouterSettings>('/api/settings', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      set({ settings, statusMessage: 'Settings saved.' })
      await Promise.all([get().refreshOverview(), get().refreshHistory(), get().refreshDevices()])
    } finally {
      set({ busy: false })
    }
  },

  testRouter: async (payload) => {
    set({ busy: true, statusMessage: 'Testing OpenWrt connection...' })
    try {
      const routerTest = await requestJson<RouterTestResult>('/api/router/test', {
        method: 'POST',
        body: JSON.stringify(payload ?? {}),
      })
      set({ routerTest, statusMessage: routerTest.message })
    } finally {
      set({ busy: false })
    }
  },
}))
