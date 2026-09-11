import { describe, expect, it } from 'vitest'
import { parseDhcpLeases, parseNeighbors, parseSystemInfo, parseWanCounters } from './parsers.js'

describe('parseWanCounters', () => {
  it('extracts rx and tx byte counters from ip link output', () => {
    const output = `
2: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    RX: bytes  packets  errors  dropped overrun mcast
    3000000    1000     2       0       0       0
    TX: bytes  packets  errors  dropped carrier collsns
    1500000    900      3       0       0       0
    `

    expect(parseWanCounters(output)).toEqual({
      rxBytes: 3000000,
      rxErrors: 2,
      txBytes: 1500000,
      txErrors: 3,
    })
  })
})

describe('parseSystemInfo', () => {
  it('parses ubus system info payload', () => {
    const output = JSON.stringify({
      uptime: 600,
      localtime: 1710000000,
      load: [6553, 9830, 13107],
      memory: {
        total: 268435456,
        available: 134217728,
      },
    })

    const result = parseSystemInfo(output)

    expect(result.uptimeSeconds).toBe(600)
    expect(result.loadAverage).toBe('0.10 / 0.15 / 0.20')
    expect(result.memoryTotalMb).toBe(256)
    expect(result.memoryUsedMb).toBe(128)
  })
})

describe('neighbor and lease parsing', () => {
  it('extracts device identity from OpenWrt text outputs', () => {
    const leases = `
1719999999 D8:3A:DD:11:22:33 192.168.1.10 living-room-tv *
1719999999 78:5F:43:AA:BB:CC 192.168.1.24 pixel-phone *
    `

    const neighbors = `
192.168.1.10 dev br-lan lladdr d8:3a:dd:11:22:33 REACHABLE
192.168.1.24 dev br-lan lladdr 78:5f:43:aa:bb:cc STALE
    `

    expect(parseDhcpLeases(leases)).toHaveLength(2)
    expect(parseNeighbors(neighbors)).toEqual([
      {
        ip: '192.168.1.10',
        mac: 'D8:3A:DD:11:22:33',
        state: 'REACHABLE',
      },
      {
        ip: '192.168.1.24',
        mac: '78:5F:43:AA:BB:CC',
        state: 'STALE',
      },
    ])
  })
})
