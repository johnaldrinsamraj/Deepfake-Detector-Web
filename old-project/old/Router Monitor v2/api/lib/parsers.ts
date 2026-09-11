type SystemInfoPayload = {
  uptime?: number
  localtime?: number
  load?: number[]
  memory?: {
    total?: number
    available?: number
  }
}

export type ParsedCounterSnapshot = {
  rxBytes: number
  txBytes: number
  rxErrors: number
  txErrors: number
}

export type ParsedSystemInfo = {
  routerTime: string
  uptimeSeconds: number
  loadAverage: string
  memoryTotalMb: number
  memoryUsedMb: number
}

export type LeaseRecord = {
  mac: string
  ip: string
  hostname?: string
}

export type NeighborRecord = {
  ip: string
  mac: string
  state: string
}

function toMb(value?: number) {
  if (!value) {
    return 0
  }

  return Math.round(value / 1024 / 1024)
}

export function parseWanCounters(raw: string): ParsedCounterSnapshot {
  const numericLines = raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => /^\d+\s+\d+\s+\d+/.test(line))

  const rxParts = numericLines[0]?.split(/\s+/) ?? []
  const txParts = numericLines[1]?.split(/\s+/) ?? []

  return {
    rxBytes: Number(rxParts[0] ?? 0),
    rxErrors: Number(rxParts[2] ?? 0),
    txBytes: Number(txParts[0] ?? 0),
    txErrors: Number(txParts[2] ?? 0),
  }
}

export function parseSystemInfo(raw: string, fallbackDate = new Date()): ParsedSystemInfo {
  let parsed: SystemInfoPayload = {}

  try {
    parsed = JSON.parse(raw) as SystemInfoPayload
  } catch {
    parsed = {}
  }

  const uptimeSeconds = Math.round(parsed.uptime ?? 0)
  const routerTime = parsed.localtime
    ? new Date(parsed.localtime * 1000).toISOString()
    : fallbackDate.toISOString()
  const loadAverage = Array.isArray(parsed.load)
    ? parsed.load
        .slice(0, 3)
        .map((value) => (value / 65535).toFixed(2))
        .join(' / ')
    : '0.00 / 0.00 / 0.00'
  const memoryTotalMb = toMb(parsed.memory?.total)
  const memoryAvailableMb = toMb(parsed.memory?.available)

  return {
    routerTime,
    uptimeSeconds,
    loadAverage,
    memoryTotalMb,
    memoryUsedMb: Math.max(memoryTotalMb - memoryAvailableMb, 0),
  }
}

export function parseDhcpLeases(raw: string): LeaseRecord[] {
  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\s+/)
      const mac = parts[1]
      const ip = parts[2]
      const hostname = parts[3]

      return {
        mac: (mac ?? '').toUpperCase(),
        ip: ip ?? '',
        hostname: hostname && hostname !== '*' ? hostname : undefined,
      }
    })
    .filter((lease) => lease.mac && lease.ip)
}

export function parseNeighbors(raw: string): NeighborRecord[] {
  const knownStates = new Set(['REACHABLE', 'STALE', 'DELAY', 'PROBE', 'PERMANENT', 'FAILED'])

  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\s+/)
      const ip = parts[0]
      const lladdrIndex = parts.indexOf('lladdr')
      const mac = lladdrIndex >= 0 ? parts[lladdrIndex + 1] : undefined
      const lastToken = parts.at(-1)
      const state = lastToken && knownStates.has(lastToken) ? lastToken : 'UNKNOWN'

      if (!ip || !mac || !/^[A-Fa-f0-9:]{17}$/.test(mac)) {
        return null
      }

      return {
        ip,
        mac: mac.toUpperCase(),
        state,
      }
    })
    .filter((record): record is NeighborRecord => Boolean(record))
}
