'use client'

import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useRouter } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { useAuth } from '@/components/providers/auth-provider'
import { watchlistAPI, type WatchlistItem, type WatchlistPayload, type WatchlistTargetAlert } from '@/lib/api'

type FormState = {
  symbol: string
  name: string
  market: string
  asset_type: string
  priority: 'low' | 'medium' | 'high'
  status: 'idea' | 'researching' | 'ready' | 'paused' | 'promoted' | 'archived'
  target_entry_min: string
  target_entry_max: string
  thesis: string
  catalyst: string
  next_review_date: string
}

const blankForm: FormState = {
  symbol: '',
  name: '',
  market: '',
  asset_type: 'unknown',
  priority: 'medium',
  status: 'idea',
  target_entry_min: '',
  target_entry_max: '',
  thesis: '',
  catalyst: '',
  next_review_date: '',
}

function toPayload(form: FormState): WatchlistPayload {
  return {
    symbol: form.symbol.trim().toUpperCase(),
    name: form.name.trim() || null,
    market: form.market.trim() || null,
    asset_type: form.asset_type.trim() || 'unknown',
    priority: form.priority,
    status: form.status,
    target_entry_min: form.target_entry_min ? Number(form.target_entry_min) : null,
    target_entry_max: form.target_entry_max ? Number(form.target_entry_max) : null,
    thesis: form.thesis.trim() || null,
    catalyst: form.catalyst.trim() || null,
    next_review_date: form.next_review_date || null,
    owned_asset_id: null,
  }
}

function fromItem(item: WatchlistItem): FormState {
  return {
    symbol: item.symbol,
    name: item.name ?? '',
    market: item.market ?? '',
    asset_type: item.asset_type,
    priority: item.priority as FormState['priority'],
    status: item.status as FormState['status'],
    target_entry_min: item.target_entry_min == null ? '' : String(item.target_entry_min),
    target_entry_max: item.target_entry_max == null ? '' : String(item.target_entry_max),
    thesis: item.thesis ?? '',
    catalyst: item.catalyst ?? '',
    next_review_date: item.next_review_date ?? '',
  }
}

function fieldStyle(multiline = false): CSSProperties {
  return {
    width: '100%',
    background: 'var(--bg-inset)',
    border: '1px solid var(--line-2)',
    color: 'var(--fg-0)',
    padding: '9px 10px',
    fontSize: 12,
    minHeight: multiline ? 72 : undefined,
  }
}

export default function WatchlistPage() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [alerts, setAlerts] = useState<WatchlistTargetAlert[]>([])
  const [form, setForm] = useState<FormState>(blankForm)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) { router.push('/login'); return }
    void load()
  }, [isAuthenticated, isLoading, router])

  async function load() {
    setLoading(true)
    setError('')
    const [itemsResult, alertsResult] = await Promise.allSettled([
      watchlistAPI.list({ limit: 200 }),
      watchlistAPI.alertEvents(),
    ])
    if (itemsResult.status === 'fulfilled') setItems(itemsResult.value)
    else setError(itemsResult.reason instanceof Error ? itemsResult.reason.message : 'Watchlist failed to load')
    setAlerts(alertsResult.status === 'fulfilled' ? alertsResult.value : [])
    setLoading(false)
  }

  async function save() {
    const payload = toPayload(form)
    if (!payload.symbol) return
    setSaving(true)
    setError('')
    setMessage('')
    try {
      if (editingId == null) await watchlistAPI.create(payload)
      else await watchlistAPI.update(editingId, payload)
      setForm(blankForm)
      setEditingId(null)
      setMessage(editingId == null ? 'Watchlist idea created.' : 'Watchlist idea updated.')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: number) {
    setError('')
    try {
      await watchlistAPI.delete(id)
      setItems(current => current.filter(item => item.id !== id))
      setMessage('Watchlist idea deleted.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  async function evaluate() {
    setMessage('')
    setError('')
    try {
      const result = await watchlistAPI.evaluateAlerts()
      setMessage(result.triggered.length ? `${result.triggered.length} target alert(s) triggered.` : 'No target alerts triggered.')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Alert evaluation failed')
    }
  }

  const activeCount = useMemo(() => items.filter(item => !['archived', 'promoted'].includes(item.status)).length, [items])

  if (isLoading || !isAuthenticated) return null

  return (
    <div className="min-h-screen">
      <Header />
      <Sidebar />
      <main className="px-4 pb-8 pt-[60px] md:ml-[220px] md:px-6 lg:px-8">
        <div className="mx-auto max-w-[1280px] space-y-4 py-4">
          <section className="panel panel-bento" style={{ padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
              <div>
                <div className="panel-header">Watchlist · idea pipeline</div>
                <h1 style={{ marginTop: 10, fontSize: 32, lineHeight: 1, fontWeight: 400, color: 'var(--fg-0)' }}>Target-entry review</h1>
                <p style={{ marginTop: 12, maxWidth: 720, fontSize: 13, lineHeight: 1.7, color: 'var(--fg-2)' }}>
                  Track non-owned ideas, thesis notes, catalysts, review dates, and target entry ranges before promotion into the owned portfolio.
                </p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="panel-header">Active ideas</div>
                <div style={{ marginTop: 10, fontSize: 32, fontWeight: 300, color: 'var(--fg-0)' }}>{activeCount}</div>
                <button type="button" className="btn-ghost" style={{ marginTop: 10 }} onClick={evaluate}>Evaluate targets</button>
              </div>
            </div>
            {error ? <div style={{ marginTop: 14, color: 'var(--pl-dn)', fontSize: 12 }}>{error}</div> : null}
            {message ? <div style={{ marginTop: 14, color: 'var(--fg-2)', fontSize: 12 }}>{message}</div> : null}
          </section>

          <section className="grid gap-4 xl:grid-cols-[0.78fr_1.22fr]">
            <div className="panel" style={{ padding: 20 }}>
              <div className="panel-header">{editingId == null ? 'Add idea' : 'Edit idea'}</div>
              <div className="grid gap-3 sm:grid-cols-2" style={{ marginTop: 14 }}>
                <input aria-label="Symbol" placeholder="Symbol" value={form.symbol} onChange={e => setForm({ ...form, symbol: e.target.value })} style={fieldStyle()} />
                <input aria-label="Name" placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} style={fieldStyle()} />
                <input aria-label="Market" placeholder="Market" value={form.market} onChange={e => setForm({ ...form, market: e.target.value })} style={fieldStyle()} />
                <input aria-label="Asset type" placeholder="Asset type" value={form.asset_type} onChange={e => setForm({ ...form, asset_type: e.target.value })} style={fieldStyle()} />
                <select aria-label="Priority" value={form.priority} onChange={e => setForm({ ...form, priority: e.target.value as FormState['priority'] })} style={fieldStyle()}>
                  <option value="low">low</option><option value="medium">medium</option><option value="high">high</option>
                </select>
                <select aria-label="Status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value as FormState['status'] })} style={fieldStyle()}>
                  <option value="idea">idea</option><option value="researching">researching</option><option value="ready">ready</option><option value="paused">paused</option><option value="promoted">promoted</option><option value="archived">archived</option>
                </select>
                <input aria-label="Target min" placeholder="Target min" type="number" value={form.target_entry_min} onChange={e => setForm({ ...form, target_entry_min: e.target.value })} style={fieldStyle()} />
                <input aria-label="Target max" placeholder="Target max" type="number" value={form.target_entry_max} onChange={e => setForm({ ...form, target_entry_max: e.target.value })} style={fieldStyle()} />
                <input aria-label="Next review date" type="date" value={form.next_review_date} onChange={e => setForm({ ...form, next_review_date: e.target.value })} style={fieldStyle()} />
              </div>
              <div style={{ marginTop: 12, display: 'grid', gap: 12 }}>
                <textarea aria-label="Thesis" placeholder="Thesis" value={form.thesis} onChange={e => setForm({ ...form, thesis: e.target.value })} style={fieldStyle(true)} />
                <textarea aria-label="Catalyst" placeholder="Catalyst" value={form.catalyst} onChange={e => setForm({ ...form, catalyst: e.target.value })} style={fieldStyle(true)} />
              </div>
              <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                <button type="button" className="btn-ghost" disabled={saving || !form.symbol.trim()} onClick={save}>{saving ? 'Saving…' : editingId == null ? 'Create' : 'Update'}</button>
                {editingId != null ? <button type="button" className="btn-ghost" onClick={() => { setEditingId(null); setForm(blankForm) }}>Cancel</button> : null}
              </div>
            </div>

            <div className="panel" style={{ padding: 0 }}>
              <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--line-1)', display: 'flex', justifyContent: 'space-between' }}>
                <span className="panel-header">Ideas</span>
                <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>{items.length} total</span>
              </div>
              {loading ? <div style={{ padding: 20, color: 'var(--fg-3)' }}>Loading watchlist…</div> : null}
              {!loading && items.length === 0 ? <div style={{ padding: 20, color: 'var(--fg-3)' }}>No ideas yet.</div> : null}
              {items.map(item => (
                <div key={item.id} style={{ padding: '14px 20px', borderBottom: '1px solid var(--line-1)' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '82px 1fr auto', gap: 12, alignItems: 'center' }}>
                    <div style={{ fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-0)', fontSize: 12 }}>{item.symbol}</div>
                    <div>
                      <div style={{ fontSize: 12.5, color: 'var(--fg-1)' }}>{item.name || item.thesis || 'Untitled idea'}</div>
                      <div style={{ marginTop: 4, fontSize: 11, color: 'var(--fg-3)' }}>
                        {item.status} · {item.priority} · target {item.target_entry_min ?? '—'}–{item.target_entry_max ?? '—'}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button type="button" className="btn-ghost" style={{ fontSize: 10, padding: '4px 8px' }} onClick={() => { setEditingId(item.id); setForm(fromItem(item)) }}>Edit</button>
                      <button type="button" className="btn-ghost" style={{ fontSize: 10, padding: '4px 8px' }} onClick={() => void remove(item.id)}>Delete</button>
                    </div>
                  </div>
                  {item.catalyst ? <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--fg-2)' }}>Catalyst: {item.catalyst}</div> : null}
                </div>
              ))}
            </div>
          </section>

          <section className="panel" style={{ padding: 20 }}>
            <div className="panel-header">Target alerts</div>
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {alerts.length === 0 ? <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>No target alerts recorded.</div> : alerts.slice(0, 8).map(alert => (
                <div key={alert.id} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 8, fontSize: 11.5, color: 'var(--fg-2)' }}>
                  {alert.message} · {new Date(alert.triggered_at).toISOString().slice(0, 16).replace('T', ' ')}
                </div>
              ))}
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
