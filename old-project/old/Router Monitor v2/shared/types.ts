export type RouterSettings = {
  host: string
  port: number
  username: string
  password?: string
  privateKey?: string
  wanInterface: string
  lanBridge: string
  pollIntervalMs: number
  dataRetentionHours: number
}

export type LiveUsageSample = {
  timestamp: string
  downloadMbps: number
  uploadMbps: number
  totalDownloadBytes: number
  totalUploadBytes: number
  wanUptimeSeconds?: number
  latencyMs?: number
  rxErrors?: number
  txErrors?: number
}

export type RouterHealth = {
  routerTime: string
  uptimeSeconds: number
  loadAverage: string
  memoryUsedMb: number
  memoryTotalMb: number
  wanStatus: 'connected' | 'degraded' | 'offline' | 'unknown'
  lastPollStatus: 'ok' | 'demo' | 'error'
  lastPollMessage: string
}

export type DeviceRecord = {
  id: string
  ip: string
  mac: string
  hostname?: string
  nickname?: string
  interface?: string
  connected: boolean
  firstSeenAt?: string
  lastSeenAt?: string
  recentRxBytes?: number
  recentTxBytes?: number
  signalDbm?: number
  banned: boolean
  banReason?: string
}

export type ImportantStats = {
  lastUpdatedAt: string
  activeDeviceCount: number
  peakDownloadMbps: number
  peakUploadMbps: number
  dailyDownloadBytes: number
  dailyUploadBytes: number
  totalSamples: number
  wanReconnects: number
  lastStorageWriteOk: boolean
}

export type StorageSummary = {
  historyEntries: number
  nicknameEntries: number
  policyEntries: number
  usageHistoryBytes: number
  lastWriteAt?: string
}

export type OverviewResponse = {
  mode: 'live' | 'demo'
  latestSample: LiveUsageSample
  health: RouterHealth
  importantStats: ImportantStats
  storage: StorageSummary
}

export type HistoryResponse = {
  samples: LiveUsageSample[]
  stats: ImportantStats
}

export type DeviceNicknamePayload = {
  ip: string
  mac: string
  nickname: string
}

export type DeviceActionPayload = {
  ip?: string
  mac: string
  reason?: string
}

export type DeviceActionResult = {
  success: boolean
  message: string
  bannedDevice?: DeviceRecord
}

export type RouterCapability = {
  key: string
  label: string
  supported: boolean
}

export type RouterTestResult = {
  success: boolean
  mode: 'live' | 'demo'
  message: string
  capabilities: RouterCapability[]
}
