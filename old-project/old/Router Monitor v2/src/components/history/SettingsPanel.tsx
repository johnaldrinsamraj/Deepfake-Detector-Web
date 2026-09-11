import { useEffect, useMemo, useState } from 'react'
import { Cpu, Database, Router, ShieldAlert } from 'lucide-react'
import type { RouterSettings, RouterTestResult } from '../../../shared/types'

type SettingsPanelProps = {
  settings: RouterSettings | null
  routerTest: RouterTestResult | null
  onSave: (payload: Partial<RouterSettings>) => Promise<void>
  onTest: (payload?: Partial<RouterSettings>) => Promise<void>
}

const emptySettings: RouterSettings = {
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

export function SettingsPanel({ settings, routerTest, onSave, onTest }: SettingsPanelProps) {
  const initial = useMemo(() => settings ?? emptySettings, [settings])
  const [draft, setDraft] = useState(initial)

  useEffect(() => {
    setDraft(initial)
  }, [initial])

  return (
    <section className="rounded-[28px] border border-white/10 bg-black/30 p-6 backdrop-blur">
      <div className="mb-5">
        <div className="text-[11px] uppercase tracking-[0.3em] text-amber-200">Router Settings</div>
        <h2 className="mt-2 font-['Orbitron'] text-xl uppercase tracking-[0.14em] text-white">
          OpenWrt link and persistence
        </h2>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {[
          ['host', 'Router host', '192.168.1.1'],
          ['port', 'SSH port', '22'],
          ['username', 'SSH user', 'root'],
          ['password', 'Password', 'optional'],
          ['wanInterface', 'WAN interface', 'wan'],
          ['lanBridge', 'LAN bridge', 'br-lan'],
          ['pollIntervalMs', 'Poll interval ms', '5000'],
          ['dataRetentionHours', 'Retention hours', '168'],
        ].map(([key, label, placeholder]) => (
          <label key={key} className="space-y-2">
            <div className="text-xs uppercase tracking-[0.24em] text-slate-400">{label}</div>
            <input
              type={key === 'password' ? 'password' : 'text'}
              value={String(draft[key as keyof RouterSettings] ?? '')}
              placeholder={placeholder}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  [key]: event.target.value,
                }))
              }
              className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none transition focus:border-amber-300/40"
            />
          </label>
        ))}
      </div>

      <label className="mt-4 block space-y-2">
        <div className="text-xs uppercase tracking-[0.24em] text-slate-400">Private key</div>
        <textarea
          value={draft.privateKey}
          onChange={(event) => setDraft((current) => ({ ...current, privateKey: event.target.value }))}
          rows={5}
          placeholder="Paste an SSH private key if you prefer key auth."
          className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none transition focus:border-amber-300/40"
        />
      </label>

      <div className="mt-5 flex flex-wrap gap-3">
        <button
          onClick={() =>
            onSave({
              ...draft,
              port: Number(draft.port),
              pollIntervalMs: Number(draft.pollIntervalMs),
              dataRetentionHours: Number(draft.dataRetentionHours),
            })
          }
          className="inline-flex items-center gap-2 rounded-2xl border border-emerald-300/20 bg-emerald-300/10 px-4 py-3 text-sm text-emerald-100 transition hover:bg-emerald-300/20"
        >
          <Database className="h-4 w-4" />
          Save settings
        </button>

        <button
          onClick={() =>
            onTest({
              ...draft,
              port: Number(draft.port),
              pollIntervalMs: Number(draft.pollIntervalMs),
              dataRetentionHours: Number(draft.dataRetentionHours),
            })
          }
          className="inline-flex items-center gap-2 rounded-2xl border border-cyan-300/20 bg-cyan-300/10 px-4 py-3 text-sm text-cyan-100 transition hover:bg-cyan-300/20"
        >
          <Router className="h-4 w-4" />
          Test connection
        </button>
      </div>

      {routerTest && (
        <div className="mt-6 rounded-2xl border border-white/8 bg-white/[0.035] p-5">
          <div className="flex items-center gap-2 text-sm text-white">
            {routerTest.success ? <Cpu className="h-4 w-4 text-emerald-300" /> : <ShieldAlert className="h-4 w-4 text-amber-200" />}
            {routerTest.message}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {routerTest.capabilities.map((capability) => (
              <div key={capability.key} className="rounded-2xl border border-white/8 bg-black/20 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.22em] text-slate-400">{capability.label}</div>
                <div className="mt-2 text-sm text-white">
                  {capability.supported ? 'Supported' : 'Unavailable'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
