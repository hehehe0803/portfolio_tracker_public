'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { watchlistAPI, type WatchlistItem } from '@/lib/api'

export function WatchlistTeaser({ compact = false }: { compact?: boolean }) {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    watchlistAPI.list({ limit: compact ? 3 : 5 })
      .then(setItems)
      .catch(e => setError(e instanceof Error ? e.message : 'Watchlist unavailable'))
  }, [compact])

  return (
    <div className="panel" style={{ padding: compact ? 16 : 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
        <div>
          <div className="panel-header">Watchlist</div>
          <div style={{ marginTop: 5, fontSize: 11.5, color: 'var(--fg-3)' }}>Non-owned ideas and target entries</div>
        </div>
        <Link href="/watchlist" style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)', textDecoration: 'none' }}>
          open →
        </Link>
      </div>
      {error ? <div style={{ marginTop: 10, color: 'var(--pl-dn)', fontSize: 11.5 }}>{error}</div> : null}
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.length === 0 && !error ? (
          <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>No watchlist ideas yet.</div>
        ) : (
          items.map(item => (
            <Link key={item.id} href="/watchlist" style={{ display: 'grid', gridTemplateColumns: '72px 1fr auto', gap: 10, alignItems: 'center', borderTop: '1px solid var(--line-1)', paddingTop: 8, color: 'inherit', textDecoration: 'none' }}>
              <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 11, color: 'var(--fg-0)' }}>{item.symbol}</span>
              <span style={{ fontSize: 11.5, color: 'var(--fg-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.name || item.thesis || item.status}
              </span>
              <span className={item.priority === 'high' ? 'badge-amber' : 'badge-dim'}>{item.target_entry_max != null ? `$${item.target_entry_max}` : item.priority}</span>
            </Link>
          ))
        )}
      </div>
    </div>
  )
}
