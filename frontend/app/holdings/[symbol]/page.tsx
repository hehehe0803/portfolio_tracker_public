'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { NotePanel } from '@/components/intelligence/NotePanel'
import { useAuth } from '@/components/providers/auth-provider'
import {
  intelligenceAPI,
  portfolioAPI,
  type ActivityEvent,
  type AssetClassification,
  type Holding,
  type PendingOrder,
  type Transaction,
} from '@/lib/api'

function fmtUsd(n: number | null | undefined, dec = 2) {
  if (n == null) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  }).format(n)
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

function fmtQty(n: number | null | undefined) {
  if (n == null) return '—'
  if (n < 0.001) return n.toExponential(2)
  if (n < 1) return n.toFixed(4)
  if (n < 100) return n.toFixed(2)
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function tone(n: number | null | undefined) {
  if (n == null || n === 0) return 'var(--fg-2)'
  return n > 0 ? 'var(--pl-up)' : 'var(--pl-dn)'
}

export default function HoldingDetailPage() {
  const params = useParams<{ symbol: string }>()
  const searchParams = useSearchParams()
  const symbol = decodeURIComponent(params.symbol || '').toUpperCase()
  const institutionParam = searchParams.get('institution') ?? ''
  const institution = institutionParam.toUpperCase()
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [holding, setHolding] = useState<Holding | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([])
  const [classification, setClassification] = useState<AssetClassification | null>(null)
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const [summaryResult, transactionsResult, pendingResult, classificationResult, activityResult] = await Promise.allSettled([
      portfolioAPI.summary(),
      portfolioAPI.transactions({ asset: symbol, institution: institutionParam || undefined, limit: 200 }),
      portfolioAPI.pendingOrders(),
      intelligenceAPI.getClassification(symbol),
      intelligenceAPI.activity({ entity_type: 'asset', entity_id: symbol, limit: 8 }),
    ])

    if (summaryResult.status === 'rejected') {
      setError(summaryResult.reason instanceof Error ? summaryResult.reason.message : 'Holding failed to load')
      setLoading(false)
      return
    }

    const match = summaryResult.value.holdings.find(h => (
      h.symbol.toUpperCase() === symbol &&
      (!institution || h.institution.toUpperCase() === institution)
    )) ?? null
    setHolding(match)
    setTransactions(transactionsResult.status === 'fulfilled' ? transactionsResult.value : [])
    setClassification(classificationResult.status === 'fulfilled' ? classificationResult.value : null)
    setActivityEvents(activityResult.status === 'fulfilled' ? activityResult.value : [])
    setPendingOrders(
      pendingResult.status === 'fulfilled'
        ? pendingResult.value.filter(order => (
            order.symbol.toUpperCase() === symbol &&
            (!institution || order.institution.toUpperCase() === institution)
          ))
        : []
    )
    setLoading(false)
  }, [institution, institutionParam, symbol])

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) {
      router.push('/login')
      return
    }
    if (!symbol) return
    void load()
  }, [isAuthenticated, isLoading, load, router, symbol])

  const noteBullets = useMemo(() => {
    if (!holding) return []
    const bullets = [
      `${holding.institution} is currently the primary visible venue for this position.`,
      `Average cost basis is ${fmtUsd(holding.avg_buy_price_usd, 2)} against current price ${fmtUsd(holding.current_price_usd, 2)}.`,
      `${fmtQty(holding.quantity)} units are currently tracked with current market value ${fmtUsd(holding.current_value_usd, 2)}.`,
    ]
    if ((holding.unrealized_pnl_pct ?? 0) < 0) {
      bullets.push('This holding is below cost basis, so the review frame should focus on thesis durability and sizing discipline.')
    } else {
      bullets.push('This holding is above cost basis, so the review frame should focus on concentration, trim rules, and what would invalidate the thesis.')
    }
    return bullets
  }, [holding])

  if (isLoading || !isAuthenticated) return null

  return (
    <div className="min-h-screen">
      <Header />
      <Sidebar />
      <main className="px-4 pb-8 pt-[60px] md:ml-[220px] md:px-6 lg:px-8">
        <div className="mx-auto max-w-[1280px] space-y-4 py-4">
          <section data-mobile-section="holding-summary" className="panel panel-bento" style={{ padding: 24 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
              <div>
                <div className="panel-header">Asset detail · v1</div>
                <h1 style={{ marginTop: 10, fontSize: 32, lineHeight: 1, fontWeight: 400, color: 'var(--fg-0)' }}>
                  {symbol || 'Holding'}
                </h1>
                <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  <span className="badge-dim">{holding?.asset_type ?? 'Unknown type'}</span>
                  <span className="badge-dim">{holding?.institution ?? 'No venue loaded'}</span>
                  <span className="badge-dim">{transactions.length} transaction{transactions.length !== 1 ? 's' : ''}</span>
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <button
                  type="button"
                  className="btn-ghost md:hidden opacity-60"
                  aria-label="Holding activity filters unavailable"
                  aria-disabled="true"
                  disabled
                  title="Holding activity filters are not available yet"
                >
                  Filters unavailable
                </button>
                <div className="panel-header">Current value</div>
                <div style={{ marginTop: 10, fontSize: 28, fontWeight: 300, color: 'var(--fg-0)' }}>
                  {holding ? fmtUsd(holding.current_value_usd, 2) : '—'}
                </div>
                <div style={{ marginTop: 6, fontFamily: 'var(--font-geist-mono)', fontSize: 11, color: tone(holding?.unrealized_pnl_pct) }}>
                  {holding ? `${fmtPct(holding.unrealized_pnl_pct)} · ${fmtUsd(holding.unrealized_pnl_usd, 2)}` : 'Loading'}
                </div>
              </div>
            </div>
            <div style={{ marginTop: 18 }}>
              <Link href="/portfolio" style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)', textDecoration: 'none' }}>
                ← back to portfolio details
              </Link>
            </div>
            {error ? (
              <div style={{ marginTop: 16, border: '1px solid rgba(201,119,102,0.28)', color: 'var(--pl-dn)', padding: '12px 14px' }}>
                {error}
              </div>
            ) : null}
          </section>

          {!loading && !holding ? (
            <section className="panel" style={{ padding: 20, color: 'var(--fg-3)' }}>
              This symbol is not currently present in the open holdings snapshot.
            </section>
          ) : null}

          <section data-mobile-section="holding-health" className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
            <div className="panel" style={{ padding: 20 }}>
              <div className="panel-header">Position summary</div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" style={{ marginTop: 14 }}>
                {[
                  { label: 'Quantity', value: fmtQty(holding?.quantity), color: 'var(--fg-0)' },
                  { label: 'Average cost', value: fmtUsd(holding?.avg_buy_price_usd, 2), color: 'var(--fg-0)' },
                  { label: 'Current price', value: fmtUsd(holding?.current_price_usd, 2), color: 'var(--fg-0)' },
                  { label: 'Unrealized', value: fmtPct(holding?.unrealized_pnl_pct), color: tone(holding?.unrealized_pnl_pct) },
                ].map(item => (
                  <div key={item.label} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 12 }}>
                    <div className="panel-header">{item.label}</div>
                    <div style={{ marginTop: 8, fontSize: 18, fontWeight: 300, color: item.color }}>{item.value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="panel" style={{ padding: 20 }}>
              <div className="panel-header">Classification</div>
              <div style={{ marginTop: 14, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                <span className="badge-dim">{classification?.asset_type ?? holding?.asset_type ?? 'unknown'}</span>
                <span className="badge-dim">{classification?.sector ?? 'No sector'}</span>
                <span className="badge-dim">{classification?.thesis_status ?? 'no thesis status'}</span>
                {(classification?.themes ?? []).map(theme => <span key={theme} className="badge-dim">{theme}</span>)}
                {(classification?.tags ?? []).map(tag => <span key={tag.id} className="badge-dim">{tag.name}</span>)}
              </div>
              <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {noteBullets.map(note => (
                  <div key={note} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10, fontSize: 11.5, color: 'var(--fg-2)', lineHeight: 1.6 }}>
                    {note}
                  </div>
                ))}
                {!holding ? (
                  <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>Waiting for holding snapshot…</div>
                ) : null}
              </div>
            </div>
          </section>

          <section data-mobile-section="holding-holdings" className="panel" style={{ padding: 20 }}>
            <div className="panel-header">Position ledger</div>
            <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--fg-2)', lineHeight: 1.6 }}>
              Compact position context appears above; execution queue and recent activity are progressively disclosed below.
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <div data-mobile-section="holding-action-surfaces" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <NotePanel entityType="asset" entityId={symbol} title={`${symbol} notes`} />
              <div className="panel" style={{ padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <div className="panel-header">Pending orders</div>
                <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
                  execution queue
                </span>
              </div>
              <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {pendingOrders.length === 0 ? (
                  <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>No pending orders for this symbol.</div>
                ) : (
                  pendingOrders.map(order => (
                    <div key={order.external_order_id} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                        <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-0)' }}>
                          {order.side} {order.order_type}
                        </span>
                        <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
                          {order.status}
                        </span>
                      </div>
                      <div style={{ marginTop: 4, fontSize: 11.5, color: 'var(--fg-3)' }}>
                        Qty {fmtQty(order.quantity)} · Limit {fmtUsd(order.limit_price, 2)} · {order.institution}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
            </div>

            <div data-mobile-section="holding-activity" className="panel" style={{ padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <div className="panel-header">Transactions</div>
                <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
                  recent fills & transfers
                </span>
              </div>
              <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {activityEvents.map(event => (
                  <div key={`event-${event.id}`} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-0)' }}>{event.source}</span>
                      <span style={{ fontSize: 11.5, color: 'var(--fg-2)' }}>{new Date(event.created_at).toISOString().slice(0, 16).replace('T', ' ')}</span>
                    </div>
                    <div style={{ marginTop: 4, fontSize: 11.5, color: 'var(--fg-3)' }}>{event.message}</div>
                  </div>
                ))}
                {transactions.length === 0 ? (
                  <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>No recent transactions for this symbol.</div>
                ) : (
                  transactions.map(tx => (
                    <div key={tx.id} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                        <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-0)' }}>
                          {tx.type.replace(/_/g, ' ')}
                        </span>
                        <span style={{ fontSize: 11.5, color: 'var(--fg-2)' }}>{new Date(tx.timestamp).toISOString().slice(0, 16).replace('T', ' ')}</span>
                      </div>
                      <div style={{ marginTop: 4, fontSize: 11.5, color: 'var(--fg-3)' }}>
                        Qty {fmtQty(tx.quantity)} · {tx.total_usd != null ? fmtUsd(tx.total_usd, 2) : 'No notional'} · {tx.institution}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
