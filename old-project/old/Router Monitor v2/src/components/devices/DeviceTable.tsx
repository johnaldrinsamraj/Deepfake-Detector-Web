import { useMemo, useState } from 'react'
import { Ban, PencilLine, PlugZap, Save, ShieldCheck, ShieldOff, Wifi } from 'lucide-react'
import type { DeviceRecord } from '../../../shared/types'

type DeviceTableProps = {
  devices: DeviceRecord[]
  onSaveNickname: (payload: { ip: string; mac: string; nickname: string }) => Promise<void>
  onAction: (action: 'disconnect' | 'ban' | 'unban', payload: { ip?: string; mac: string; reason?: string }) => Promise<void>
}

export function DeviceTable({ devices, onSaveNickname, onAction }: DeviceTableProps) {
  const [search, setSearch] = useState('')
  const [nicknameDrafts, setNicknameDrafts] = useState<Record<string, string>>({})

  const filteredDevices = useMemo(() => {
    const query = search.trim().toLowerCase()

    if (!query) {
      return devices
    }

    return devices.filter((device) =>
      [device.ip, device.mac, device.hostname, device.nickname]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    )
  }, [devices, search])

  return (
    <section className="rounded-[28px] border border-white/10 bg-black/30 p-6 backdrop-blur">
      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.3em] text-cyan-200">Connected Devices</div>
          <h2 className="mt-2 font-['Orbitron'] text-xl uppercase tracking-[0.14em] text-white">
            Client roster and control plane
          </h2>
        </div>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search IP, MAC, host, nickname"
          className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none transition focus:border-cyan-300/40 md:max-w-xs"
        />
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-separate border-spacing-y-3">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-[0.28em] text-slate-400">
              <th className="px-3">Device</th>
              <th className="px-3">Address</th>
              <th className="px-3">Nickname</th>
              <th className="px-3">State</th>
              <th className="px-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredDevices.map((device) => {
              const draft = nicknameDrafts[device.id] ?? device.nickname ?? ''

              return (
                <tr key={device.id} className="rounded-2xl bg-white/[0.035] text-sm text-slate-200">
                  <td className="rounded-l-3xl border border-r-0 border-white/8 px-3 py-4 align-top">
                    <div className="flex items-start gap-3">
                      <div className="mt-1 rounded-2xl border border-white/10 bg-black/20 p-2">
                        <Wifi className="h-4 w-4 text-cyan-200" />
                      </div>
                      <div>
                        <div className="font-medium text-white">{device.hostname || 'Unknown device'}</div>
                        <div className="mt-1 text-xs text-slate-400">{device.interface || 'LAN'}</div>
                      </div>
                    </div>
                  </td>
                  <td className="border border-l-0 border-r-0 border-white/8 px-3 py-4 align-top">
                    <div>{device.ip}</div>
                    <div className="mt-1 text-xs text-slate-400">{device.mac}</div>
                  </td>
                  <td className="border border-l-0 border-r-0 border-white/8 px-3 py-4 align-top">
                    <div className="flex gap-2">
                      <input
                        value={draft}
                        onChange={(event) =>
                          setNicknameDrafts((current) => ({
                            ...current,
                            [device.id]: event.target.value,
                          }))
                        }
                        placeholder="Friendly nickname"
                        className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none transition focus:border-cyan-300/40"
                      />
                      <button
                        onClick={() => onSaveNickname({ ip: device.ip, mac: device.mac, nickname: draft.trim() })}
                        className="inline-flex items-center gap-2 rounded-xl border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-xs text-cyan-100 transition hover:bg-cyan-300/20"
                      >
                        <Save className="h-4 w-4" />
                        Save
                      </button>
                    </div>
                  </td>
                  <td className="border border-l-0 border-r-0 border-white/8 px-3 py-4 align-top">
                    <div className="flex flex-wrap gap-2">
                      <span
                        className={`rounded-full px-3 py-1 text-xs ${
                          device.connected
                            ? 'bg-emerald-400/15 text-emerald-100'
                            : 'bg-slate-500/20 text-slate-300'
                        }`}
                      >
                        {device.connected ? 'Online' : 'Offline'}
                      </span>
                      <span
                        className={`rounded-full px-3 py-1 text-xs ${
                          device.banned ? 'bg-red-500/20 text-red-100' : 'bg-cyan-300/10 text-cyan-100'
                        }`}
                      >
                        {device.banned ? 'Banned' : 'Allowed'}
                      </span>
                    </div>
                    <div className="mt-3 text-xs text-slate-400">
                      Last seen: {device.lastSeenAt ? new Date(device.lastSeenAt).toLocaleString() : 'n/a'}
                    </div>
                  </td>
                  <td className="rounded-r-3xl border border-l-0 border-white/8 px-3 py-4 align-top">
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => onAction('disconnect', { ip: device.ip, mac: device.mac })}
                        className="inline-flex items-center gap-2 rounded-xl border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs text-amber-100 transition hover:bg-amber-300/20"
                      >
                        <PlugZap className="h-4 w-4" />
                        Disconnect
                      </button>

                      {!device.banned ? (
                        <button
                          onClick={() => onAction('ban', { ip: device.ip, mac: device.mac, reason: 'Blocked from dashboard' })}
                          className="inline-flex items-center gap-2 rounded-xl border border-red-400/20 bg-red-400/10 px-3 py-2 text-xs text-red-100 transition hover:bg-red-400/20"
                        >
                          <Ban className="h-4 w-4" />
                          Ban
                        </button>
                      ) : (
                        <button
                          onClick={() => onAction('unban', { ip: device.ip, mac: device.mac })}
                          className="inline-flex items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100 transition hover:bg-emerald-400/20"
                        >
                          <ShieldOff className="h-4 w-4" />
                          Unban
                        </button>
                      )}
                    </div>
                    <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
                      {device.nickname ? <PencilLine className="h-3.5 w-3.5" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                      {device.nickname || 'No nickname saved yet'}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
