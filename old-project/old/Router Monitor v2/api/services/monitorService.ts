import path from 'path'
import type {
  DeviceActionPayload,
  DeviceActionResult,
  DeviceNicknamePayload,
  DeviceRecord,
  HistoryResponse,
  ImportantStats,
  LiveUsageSample,
  OverviewResponse,
  RouterSettings,
  RouterTestResult,
  StorageSummary,
} from '../../shared/types.js'
import { fileSize, readJsonFile, writeJsonFile } from '../lib/jsonStore.js'
import { OpenWrtSshClient } from '../lib/openwrt.js'

type NicknameEntry = DeviceNicknamePayload & {
  updatedAt: string
}

type PolicyEntry = {
  mac: string
  ip?: string
  reason?: string
  createdAt: string
}

const DEFAULT_SETTINGS: RouterSettings = {
  host: '',
  port: 22,
  username: 'root',
  password: '',
  privateKey: '',
  wanInterface: 'wan',
  lanBridge: 'br-lan',
  pollIntervalMs: 5000,
  dataRetentionHours: 168,
}

function defaultImportantStats(): ImportantStats {
  return {
    lastUpdatedAt: new Date(0).toISOString(),
    activeDeviceCount: 0,
    peakDownloadMbps: 0,
    peakUploadMbps: 0,
    dailyDownloadBytes: 0,
    dailyUploadBytes: 0,
    totalSamples: 0,
    wanReconnects: 0,
    lastStorageWriteOk: true,
  }
}

function emptySample(): LiveUsageSample {
  return {
    timestamp: new Date().toISOString(),
    downloadMbps: 0,
    uploadMbps: 0,
    totalDownloadBytes: 0,
    totalUploadBytes: 0,
    latencyMs: 0,
    rxErrors: 0,
    txErrors: 0,
    wanUptimeSeconds: 0,
  }
}

export class MonitorService {
  private readonly client = new OpenWrtSshClient()

  private readonly dataDir = path.join(process.cwd(), 'data')
  private readonly settingsPath = path.join(this.dataDir, 'settings.json')
  private readonly nicknamesPath = path.join(this.dataDir, 'nicknames.json')
  private readonly policiesPath = path.join(this.dataDir, 'device-policies.json')
  private readonly historyPath = path.join(this.dataDir, 'usage-history.json')
  private readonly statsPath = path.join(this.dataDir, 'important-stats.json')

  private settings = { ...DEFAULT_SETTINGS }
  private nicknames: NicknameEntry[] = []
  private policies: PolicyEntry[] = []
  private history: LiveUsageSample[] = []
  private stats: ImportantStats = defaultImportantStats()
  private devices = new Map<string, DeviceRecord>()
  private latestSample: LiveUsageSample = emptySample()
  private latestMode: 'live' | 'demo' = 'demo'
  private latestMessage = 'Waiting for first router poll.'
  private latestSystemInfo = {
    routerTime: new Date().toISOString(),
    uptimeSeconds: 0,
    loadAverage: '0.00 / 0.00 / 0.00',
    memoryUsedMb: 0,
    memoryTotalMb: 0,
  }
  private lastWriteAt?: string
  private lastCounterSnapshot?: { timestamp: number; rxBytes: number; txBytes: number; uptimeSeconds: number }
  private interval?: NodeJS.Timeout
  private initialized = false

  private async ensureInitialized() {
    if (this.initialized) {
      return
    }

    this.settings = { ...DEFAULT_SETTINGS, ...(await readJsonFile(this.settingsPath, DEFAULT_SETTINGS)) }
    this.nicknames = await readJsonFile(this.nicknamesPath, [] as NicknameEntry[])
    this.policies = await readJsonFile(this.policiesPath, [] as PolicyEntry[])
    this.history = await readJsonFile(this.historyPath, [] as LiveUsageSample[])
    this.stats = { ...defaultImportantStats(), ...(await readJsonFile(this.statsPath, defaultImportantStats())) }
    this.latestSample = this.history[this.history.length - 1] ?? emptySample()
    this.initialized = true
    await this.pollNow()
    this.schedulePolling()
  }

  private schedulePolling() {
    if (this.interval) {
      clearInterval(this.interval)
    }

    this.interval = setInterval(() => {
      void this.pollNow()
    }, Math.max(this.settings.pollIntervalMs, 3000))
  }

  private nicknameForDevice(ip: string, mac: string) {
    return this.nicknames.find((entry) => entry.mac === mac || entry.ip === ip)?.nickname
  }

  private policyForMac(mac: string) {
    return this.policies.find((entry) => entry.mac === mac)
  }

  private async persist() {
    await Promise.all([
      writeJsonFile(this.settingsPath, this.settings),
      writeJsonFile(this.nicknamesPath, this.nicknames),
      writeJsonFile(this.policiesPath, this.policies),
      writeJsonFile(this.historyPath, this.history),
      writeJsonFile(this.statsPath, this.stats),
    ])
    this.lastWriteAt = new Date().toISOString()
  }

  private async pollNow() {
    await this.ensureInitialized()

    const snapshot = await this.client.fetchSnapshot(this.settings)
    const now = new Date(snapshot.collectedAt)
    const previous = this.lastCounterSnapshot
    const deltaSeconds = previous ? Math.max((now.getTime() - previous.timestamp) / 1000, 1) : 1
    const deltaRx = previous ? snapshot.counters.rxBytes - previous.rxBytes : 0
    const deltaTx = previous ? snapshot.counters.txBytes - previous.txBytes : 0

    if (
      previous &&
      snapshot.system.uptimeSeconds < previous.uptimeSeconds &&
      snapshot.mode === 'live'
    ) {
      this.stats.wanReconnects += 1
    }

    const latestSample: LiveUsageSample = {
      timestamp: snapshot.collectedAt,
      downloadMbps: deltaRx >= 0 ? Number(((deltaRx * 8) / deltaSeconds / 1000000).toFixed(2)) : 0,
      uploadMbps: deltaTx >= 0 ? Number(((deltaTx * 8) / deltaSeconds / 1000000).toFixed(2)) : 0,
      totalDownloadBytes: snapshot.counters.rxBytes,
      totalUploadBytes: snapshot.counters.txBytes,
      latencyMs: undefined,
      rxErrors: snapshot.counters.rxErrors,
      txErrors: snapshot.counters.txErrors,
      wanUptimeSeconds: snapshot.system.uptimeSeconds,
    }

    this.latestSample = latestSample
    this.latestMode = snapshot.mode
    this.latestMessage = snapshot.message
    this.latestSystemInfo = snapshot.system
    this.lastCounterSnapshot = {
      timestamp: now.getTime(),
      rxBytes: snapshot.counters.rxBytes,
      txBytes: snapshot.counters.txBytes,
      uptimeSeconds: snapshot.system.uptimeSeconds,
    }

    this.history.push(latestSample)
    const retentionMs = this.settings.dataRetentionHours * 60 * 60 * 1000
    this.history = this.history.filter((sample) => now.getTime() - new Date(sample.timestamp).getTime() <= retentionMs)

    const seenKeys = new Set<string>()
    for (const device of snapshot.devices) {
      const key = device.mac || device.ip
      const existing = this.devices.get(key)
      const policy = this.policyForMac(device.mac)
      this.devices.set(key, {
        id: key,
        ip: device.ip,
        mac: device.mac,
        hostname: device.hostname,
        nickname: this.nicknameForDevice(device.ip, device.mac),
        interface: device.interface,
        connected: true,
        firstSeenAt: existing?.firstSeenAt ?? snapshot.collectedAt,
        lastSeenAt: snapshot.collectedAt,
        recentRxBytes: latestSample.totalDownloadBytes,
        recentTxBytes: latestSample.totalUploadBytes,
        banned: Boolean(policy),
        banReason: policy?.reason,
      })
      seenKeys.add(key)
    }

    for (const [key, device] of this.devices.entries()) {
      if (!seenKeys.has(key)) {
        this.devices.set(key, {
          ...device,
          connected: false,
        })
      }
    }

    this.stats = {
      ...this.stats,
      lastUpdatedAt: snapshot.collectedAt,
      activeDeviceCount: snapshot.devices.length,
      peakDownloadMbps: Math.max(this.stats.peakDownloadMbps, latestSample.downloadMbps),
      peakUploadMbps: Math.max(this.stats.peakUploadMbps, latestSample.uploadMbps),
      dailyDownloadBytes: latestSample.totalDownloadBytes,
      dailyUploadBytes: latestSample.totalUploadBytes,
      totalSamples: this.history.length,
      lastStorageWriteOk: true,
    }

    try {
      await this.persist()
    } catch {
      this.stats.lastStorageWriteOk = false
    }
  }

  async getOverview(): Promise<OverviewResponse> {
    await this.ensureInitialized()
    const storage = await this.getStorageSummary()

    return {
      mode: this.latestMode,
      latestSample: this.latestSample,
      health: {
        routerTime: this.latestSystemInfo.routerTime,
        uptimeSeconds: this.latestSystemInfo.uptimeSeconds,
        loadAverage: this.latestSystemInfo.loadAverage,
        memoryUsedMb: this.latestSystemInfo.memoryUsedMb,
        memoryTotalMb: this.latestSystemInfo.memoryTotalMb,
        wanStatus: this.latestMode === 'live' ? 'connected' : 'unknown',
        lastPollStatus: this.latestMode === 'live' ? 'ok' : 'demo',
        lastPollMessage: this.latestMessage,
      },
      importantStats: this.stats,
      storage,
    }
  }

  async getLiveUsage(limit = 40) {
    await this.ensureInitialized()
    return this.history.slice(-limit)
  }

  async getUsageHistory(range = '24h'): Promise<HistoryResponse> {
    await this.ensureInitialized()
    const hours = range === '7d' ? 168 : range === '1h' ? 1 : 24
    const cutoff = Date.now() - hours * 60 * 60 * 1000

    return {
      samples: this.history.filter((sample) => new Date(sample.timestamp).getTime() >= cutoff),
      stats: this.stats,
    }
  }

  async getDevices() {
    await this.ensureInitialized()
    return Array.from(this.devices.values()).sort((left, right) => Number(right.connected) - Number(left.connected))
  }

  async setNickname(payload: DeviceNicknamePayload) {
    await this.ensureInitialized()
    const entry: NicknameEntry = {
      ...payload,
      mac: payload.mac.toUpperCase(),
      updatedAt: new Date().toISOString(),
    }

    this.nicknames = this.nicknames.filter((item) => item.mac !== entry.mac && item.ip !== entry.ip)
    this.nicknames.push(entry)

    for (const [key, device] of this.devices.entries()) {
      if (device.mac === entry.mac || device.ip === entry.ip) {
        this.devices.set(key, { ...device, nickname: entry.nickname })
      }
    }

    await this.persist()
    return entry
  }

  async getSettings() {
    await this.ensureInitialized()
    return this.settings
  }

  async updateSettings(nextSettings: Partial<RouterSettings>) {
    await this.ensureInitialized()
    this.settings = {
      ...this.settings,
      ...nextSettings,
      port: Number(nextSettings.port ?? this.settings.port),
      pollIntervalMs: Number(nextSettings.pollIntervalMs ?? this.settings.pollIntervalMs),
      dataRetentionHours: Number(nextSettings.dataRetentionHours ?? this.settings.dataRetentionHours),
    }
    await this.persist()
    this.schedulePolling()
    await this.pollNow()
    return this.settings
  }

  async testRouter(settingsOverride?: Partial<RouterSettings>): Promise<RouterTestResult> {
    await this.ensureInitialized()
    return await this.client.testConnection({ ...this.settings, ...settingsOverride })
  }

  async disconnectDevice(payload: DeviceActionPayload): Promise<DeviceActionResult> {
    await this.ensureInitialized()
    const message = await this.client.disconnectDevice(this.settings, payload)
    return { success: !message.toLowerCase().includes('not'), message }
  }

  async banDevice(payload: DeviceActionPayload): Promise<DeviceActionResult> {
    await this.ensureInitialized()
    const policy: PolicyEntry = {
      mac: payload.mac.toUpperCase(),
      ip: payload.ip,
      reason: payload.reason,
      createdAt: new Date().toISOString(),
    }
    this.policies = this.policies.filter((entry) => entry.mac !== policy.mac)
    this.policies.push(policy)
    const message = await this.client.banDevice(this.settings, payload)

    for (const [key, device] of this.devices.entries()) {
      if (device.mac === policy.mac) {
        this.devices.set(key, { ...device, banned: true, banReason: policy.reason })
      }
    }

    await this.persist()

    return {
      success: true,
      message,
      bannedDevice: Array.from(this.devices.values()).find((device) => device.mac === policy.mac),
    }
  }

  async unbanDevice(payload: DeviceActionPayload): Promise<DeviceActionResult> {
    await this.ensureInitialized()
    this.policies = this.policies.filter((entry) => entry.mac !== payload.mac.toUpperCase())
    const message = await this.client.unbanDevice(this.settings, payload)

    for (const [key, device] of this.devices.entries()) {
      if (device.mac === payload.mac.toUpperCase()) {
        this.devices.set(key, { ...device, banned: false, banReason: undefined })
      }
    }

    await this.persist()
    return { success: true, message }
  }

  async getStorageSummary(): Promise<StorageSummary> {
    await this.ensureInitialized()
    return {
      historyEntries: this.history.length,
      nicknameEntries: this.nicknames.length,
      policyEntries: this.policies.length,
      usageHistoryBytes: await fileSize(this.historyPath),
      lastWriteAt: this.lastWriteAt,
    }
  }
}

export const monitorService = new MonitorService()
