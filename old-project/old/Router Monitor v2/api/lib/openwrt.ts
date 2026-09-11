import { Client } from 'ssh2'
import type {
  DeviceActionPayload,
  RouterCapability,
  RouterSettings,
  RouterTestResult,
} from '../../shared/types.js'
import {
  parseDhcpLeases,
  parseNeighbors,
  parseSystemInfo,
  parseWanCounters,
} from './parsers.js'

type RemoteResult = {
  stdout: string
  stderr: string
  code: number | null
}

export type RouterSnapshot = {
  mode: 'live' | 'demo'
  message: string
  collectedAt: string
  counters: ReturnType<typeof parseWanCounters>
  system: ReturnType<typeof parseSystemInfo>
  devices: Array<{
    ip: string
    mac: string
    hostname?: string
    interface?: string
  }>
}

function escapeShellValue(value: string) {
  return `'${value.replace(/'/g, `'\\''`)}'`
}

const DEFAULT_REMOTE_PATH = '/usr/sbin:/usr/bin:/sbin:/bin'

function isConfigured(settings: RouterSettings) {
  return Boolean(settings.host && settings.username)
}

function createDemoSnapshot(message: string): RouterSnapshot {
  const now = new Date()
  const seconds = Math.floor(now.getTime() / 1000)
  const wave = Math.sin(seconds / 12)
  const burst = Math.cos(seconds / 18)
  const downloadMbps = Math.max(28 + wave * 12 + burst * 6, 2)
  const uploadMbps = Math.max(5 + burst * 2.5 + wave, 0.5)

  return {
    mode: 'demo',
    message,
    collectedAt: now.toISOString(),
    counters: {
      rxBytes: Math.round(downloadMbps * 125000 * 60),
      txBytes: Math.round(uploadMbps * 125000 * 60),
      rxErrors: 0,
      txErrors: 0,
    },
    system: {
      routerTime: now.toISOString(),
      uptimeSeconds: 86400 + seconds % 5400,
      loadAverage: '0.08 / 0.12 / 0.18',
      memoryTotalMb: 256,
      memoryUsedMb: 143,
    },
    devices: [
      {
        ip: '192.168.1.10',
        mac: 'D8:3A:DD:11:22:33',
        hostname: 'Living-Room-TV',
        interface: 'br-lan',
      },
      {
        ip: '192.168.1.24',
        mac: '78:5F:43:AA:BB:CC',
        hostname: 'Pixel-Phone',
        interface: 'br-lan',
      },
      {
        ip: '192.168.1.44',
        mac: 'F0:2F:74:12:34:56',
        hostname: 'Work-Laptop',
        interface: 'br-lan',
      },
    ],
  }
}

async function createConnection(settings: RouterSettings) {
  const client = new Client()

  await new Promise<void>((resolve, reject) => {
    client
      .on('ready', () => resolve())
      .on('error', (error) => reject(error))
      .connect({
        host: settings.host,
        port: settings.port,
        username: settings.username,
        password: settings.password || undefined,
        privateKey: settings.privateKey || undefined,
        readyTimeout: 8000,
      })
  })

  return client
}

async function runRemoteCommand(client: Client, command: string): Promise<RemoteResult> {
  return await new Promise((resolve, reject) => {
    const wrapped = `export PATH=${DEFAULT_REMOTE_PATH}:$PATH; ${command}`
    client.exec(`sh -lc ${escapeShellValue(wrapped)}`, (error, stream) => {
      if (error) {
        reject(error)
        return
      }

      let stdout = ''
      let stderr = ''
      let code: number | null = null

      stream
        .on('close', (exitCode) => {
          code = typeof exitCode === 'number' ? exitCode : null
          resolve({ stdout, stderr, code })
        })
        .on('data', (chunk: Buffer) => {
          stdout += chunk.toString('utf8')
        })

      stream.stderr.on('data', (chunk: Buffer) => {
        stderr += chunk.toString('utf8')
      })
    })
  })
}

async function withClient<T>(settings: RouterSettings, callback: (client: Client) => Promise<T>) {
  const client = await createConnection(settings)

  try {
    return await callback(client)
  } finally {
    client.end()
  }
}

function mergeDevices(neighborOutput: string, leaseOutput: string, lanBridge: string) {
  const neighbors = parseNeighbors(neighborOutput)
  const leases = parseDhcpLeases(leaseOutput)

  const hostnameByMac = new Map(leases.map((lease) => [lease.mac, lease.hostname]))
  const hostnameByIp = new Map(leases.map((lease) => [lease.ip, lease.hostname]))

  return neighbors.map((neighbor) => ({
    ip: neighbor.ip,
    mac: neighbor.mac,
    hostname: hostnameByMac.get(neighbor.mac) ?? hostnameByIp.get(neighbor.ip),
    interface: lanBridge,
  }))
}

function buildNftBanScript(mac: string) {
  return `
if command -v nft >/dev/null 2>&1; then
  nft list table inet app_guard >/dev/null 2>&1 || nft add table inet app_guard
  nft list set inet app_guard blocked_macs >/dev/null 2>&1 || nft 'add set inet app_guard blocked_macs { type ether_addr; }'
  nft list chain inet app_guard forward >/dev/null 2>&1 || nft 'add chain inet app_guard forward { type filter hook forward priority -5; policy accept; }'
  nft list chain inet app_guard input >/dev/null 2>&1 || nft 'add chain inet app_guard input { type filter hook input priority -5; policy accept; }'
  nft list chain inet app_guard forward | grep -q '@blocked_macs' || nft 'add rule inet app_guard forward ether saddr @blocked_macs drop'
  nft list chain inet app_guard input | grep -q '@blocked_macs' || nft 'add rule inet app_guard input ether saddr @blocked_macs drop'
  nft add element inet app_guard blocked_macs { ${mac} }
  exit 0
fi

if command -v iptables >/dev/null 2>&1; then
  iptables -C FORWARD -m mac --mac-source ${mac} -j DROP >/dev/null 2>&1 || iptables -I FORWARD -m mac --mac-source ${mac} -j DROP
  iptables -C INPUT -m mac --mac-source ${mac} -j DROP >/dev/null 2>&1 || iptables -I INPUT -m mac --mac-source ${mac} -j DROP
  exit 0
fi

exit 1
`.trim()
}

function buildNftUnbanScript(mac: string) {
  return `
if command -v nft >/dev/null 2>&1; then
  nft delete element inet app_guard blocked_macs { ${mac} } >/dev/null 2>&1 || true
  exit 0
fi

if command -v iptables >/dev/null 2>&1; then
  iptables -D FORWARD -m mac --mac-source ${mac} -j DROP >/dev/null 2>&1 || true
  iptables -D INPUT -m mac --mac-source ${mac} -j DROP >/dev/null 2>&1 || true
  exit 0
fi

exit 1
`.trim()
}

function buildWanCountersCommand(wanInterface: string) {
  const iface = escapeShellValue(wanInterface)
  return `
WAN_IFACE=${iface}
if ip -s link show dev "$WAN_IFACE" >/dev/null 2>&1; then
  ip -s link show dev "$WAN_IFACE" 2>/dev/null || true
else
  rx_bytes=$(cat "/sys/class/net/$WAN_IFACE/statistics/rx_bytes" 2>/dev/null || echo 0)
  tx_bytes=$(cat "/sys/class/net/$WAN_IFACE/statistics/tx_bytes" 2>/dev/null || echo 0)
  rx_errors=$(cat "/sys/class/net/$WAN_IFACE/statistics/rx_errors" 2>/dev/null || echo 0)
  tx_errors=$(cat "/sys/class/net/$WAN_IFACE/statistics/tx_errors" 2>/dev/null || echo 0)
  echo "$rx_bytes 0 $rx_errors"
  echo "$tx_bytes 0 $tx_errors"
fi
`.trim()
}

export class OpenWrtSshClient {
  async fetchSnapshot(settings: RouterSettings): Promise<RouterSnapshot> {
    if (!isConfigured(settings)) {
      return createDemoSnapshot('Router settings are incomplete. Showing demo data until you save a valid connection.')
    }

    try {
      return await withClient(settings, async (client) => {
        const [systemInfo, wanCounters, neighbors, leases] = await Promise.all([
          runRemoteCommand(client, 'ubus call system info 2>/dev/null || true'),
          runRemoteCommand(client, buildWanCountersCommand(settings.wanInterface)),
          runRemoteCommand(client, `ip neigh show dev ${escapeShellValue(settings.lanBridge)} 2>/dev/null || true`),
          runRemoteCommand(client, 'cat /tmp/dhcp.leases 2>/dev/null || true'),
        ])

        return {
          mode: 'live',
          message: 'Connected to OpenWrt over SSH.',
          collectedAt: new Date().toISOString(),
          counters: parseWanCounters(wanCounters.stdout),
          system: parseSystemInfo(systemInfo.stdout, new Date()),
          devices: mergeDevices(neighbors.stdout, leases.stdout, settings.lanBridge),
        }
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown OpenWrt connection error'
      return createDemoSnapshot(`Router connection failed: ${message}`)
    }
  }

  async testConnection(settings: RouterSettings): Promise<RouterTestResult> {
    if (!isConfigured(settings)) {
      return {
        success: false,
        mode: 'demo',
        message: 'Host and username are required before a live OpenWrt test can run.',
        capabilities: [],
      }
    }

    try {
      const capabilities = await withClient(settings, async (client) => {
        const checks: Array<[string, string, string]> = [
          ['ubus', 'UBus system info', 'command -v ubus >/dev/null 2>&1 && echo yes || echo no'],
          ['ip', 'IP route and neighbor tools', 'command -v ip >/dev/null 2>&1 && echo yes || echo no'],
          ['nft', 'NFTables ban support', 'command -v nft >/dev/null 2>&1 && echo yes || echo no'],
          ['hostapd', 'Wireless disconnect support', 'command -v hostapd_cli >/dev/null 2>&1 && echo yes || echo no'],
        ]

        const results: RouterCapability[] = []

        for (const [key, label, command] of checks) {
          const result = await runRemoteCommand(client, command)
          results.push({
            key,
            label,
            supported: result.stdout.trim() === 'yes',
          })
        }

        return results
      })

      return {
        success: true,
        mode: 'live',
        message: 'OpenWrt connection succeeded.',
        capabilities,
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown OpenWrt connection error'
      return {
        success: false,
        mode: 'demo',
        message: `OpenWrt test failed: ${message}`,
        capabilities: [],
      }
    }
  }

  async disconnectDevice(settings: RouterSettings, payload: DeviceActionPayload) {
    if (!isConfigured(settings)) {
      return 'Router is not configured yet. Save settings first, then run disconnect.'
    }

    const mac = payload.mac.toUpperCase()
    const script = `
if command -v hostapd_cli >/dev/null 2>&1 && command -v iw >/dev/null 2>&1; then
  hit=0
  for ifc in $(iw dev | awk '$1 == "Interface" { print $2 }'); do
    if hostapd_cli -i "$ifc" disassociate ${mac} >/dev/null 2>&1; then
      hit=1
    fi
  done
  if [ "$hit" = "1" ]; then
    exit 0
  fi
fi
exit 1
`.trim()

    try {
      const result = await withClient(settings, (client) => runRemoteCommand(client, script))
      return result.code === 0
        ? `Disconnect command sent for ${mac}.`
        : `OpenWrt did not expose a supported disconnect command for ${mac}.`
    } catch (error) {
      return error instanceof Error ? error.message : 'Disconnect action failed'
    }
  }

  async banDevice(settings: RouterSettings, payload: DeviceActionPayload) {
    if (!isConfigured(settings)) {
      return 'Router is not configured yet. Save settings first, then run ban.'
    }

    const mac = payload.mac.toUpperCase()

    try {
      const result = await withClient(settings, (client) => runRemoteCommand(client, buildNftBanScript(mac)))
      return result.code === 0
        ? `Ban policy applied on OpenWrt for ${mac}.`
        : `OpenWrt ban policy could not be applied for ${mac}.`
    } catch (error) {
      return error instanceof Error ? error.message : 'Ban action failed'
    }
  }

  async unbanDevice(settings: RouterSettings, payload: DeviceActionPayload) {
    if (!isConfigured(settings)) {
      return 'Router is not configured yet. Save settings first, then run unban.'
    }

    const mac = payload.mac.toUpperCase()

    try {
      const result = await withClient(settings, (client) => runRemoteCommand(client, buildNftUnbanScript(mac)))
      return result.code === 0
        ? `Ban policy removed on OpenWrt for ${mac}.`
        : `OpenWrt unban policy could not be removed for ${mac}.`
    } catch (error) {
      return error instanceof Error ? error.message : 'Unban action failed'
    }
  }
}
