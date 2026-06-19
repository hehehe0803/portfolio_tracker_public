'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { NotePanel } from '@/components/intelligence/NotePanel'
import { WatchlistTeaser } from '@/components/intelligence/WatchlistTeaser'
import { useAuth } from '@/components/providers/auth-provider'
import {
  intelligenceAPI,
  portfolioAPI,
  syncAPI,
  type ActivityEvent,
  type PendingOrder,
  type PerformanceSummary,
  type PortfolioSummary,
  type SyncStatus,
  type Transaction,
} from '@/lib/api'

const TRANSACTION_PAGE_SIZE = 500

async function loadAllTransactions(): Promise<Transaction[]> {
  const all: Transaction[] = []
  let offset = 0
  while (true) {
    const batch = await portfolioAPI.transactions({ limit: TRANSACTION_PAGE_SIZE, offset })
    all.push(...batch)
    if (batch.length < TRANSACTION_PAGE_SIZE) return all
    offset += TRANSACTION_PAGE_SIZE
  }
}

function fmtUsd(n: number | null | undefined, dec = 0) {
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

function tone(n: number | null | undefined) {
  if (n == null || n === 0) return 'var(--fg-2)'
  return n > 0 ? 'var(--pl-up)' : 'var(--pl-dn)'
}

export default function PortfolioDetailsPage() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [performanceSummary, setPerformanceSummary] = useState<PerformanceSummary | null>(null)
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([])
  const [syncStatuses, setSyncStatuses] = useState<SyncStatus[]>([])
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([])
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) {
      router.push('/login')
      return
    }
    void load()
  }, [isAuthenticated, isLoading, router])

  async function load() {
    setLoading(true)
    setError('')
    const [summaryResult, transactionsResult, perfResult, pendingResult, syncResult, activityResult] = await Promise.allSettled([
      portfolioAPI.summary(),
      loadAllTransactions(),
      portfolioAPI.performanceSummary(),
      portfolioAPI.pendingOrders(),
      syncAPI.status(),
      intelligenceAPI.activity({ limit: 8 }),
    ])

    if (summaryResult.status === 'rejected') {
      const err = summaryResult.reason
      setError(err instanceof Error ? err.message : 'Portfolio details failed to load')
      setLoading(false)
      return
    }

    if (transactionsResult.status === 'rejected') {
      const err = transactionsResult.reason
      setError(err instanceof Error ? err.message : 'Portfolio details failed to load')
      setLoading(false)
      return
    }

    setSummary(summaryResult.value)
    setTransactions(transactionsResult.value)
    setPerformanceSummary(perfResult.status === 'fulfilled' ? perfResult.value : null)
    setPendingOrders(pendingResult.status === 'fulfilled' ? pendingResult.value : [])
    setSyncStatuses(syncResult.status === 'fulfilled' ? syncResult.value : [])
    setActivityEvents(activityResult.status === 'fulfilled' ? activityResult.value : [])
    setLoading(false)
  }

  const groupedHoldings = useMemo(() => {
    if (!summary) return []
    const total = summary.total_value_usd || 1
    const groups = new Map<string, { name: string; value: number; holdings: PortfolioSummary['holdings'] }>()
    for (const holding of summary.holdings) {
      const key = holding.asset_type || 'other'
      const existing = groups.get(key)
      if (existing) {
        existing.value += holding.current_value_usd ?? 0
        existing.holdings.push(holding)
      } else {
        groups.set(key, {
          name: key,
          value: holding.current_value_usd ?? 0,
          holdings: [holding],
        })
      }
    }

    return [...groups.values()]
      .sort((a, b) => b.value - a.value)
      .map(group => ({
        ...group,
        weightPct: (group.value / total) * 100,
        holdings: group.holdings.sort((a, b) => (b.current_value_usd ?? 0) - (a.current_value_usd ?? 0)),
      }))
  }, [summary])

  const recentTransactions = transactions.slice(0, 5)
  const topHoldings = [...(summary?.holdings ?? [])]
    .sort((a, b) => (b.current_value_usd ?? 0) - (a.current_value_usd ?? 0))
    .slice(0, 4)

  if (isLoading || !isAuthenticated) {
    return null
  }

  return (
    <div className="min-h-screen">
      <Header />
      <Sidebar />
      <main className="px-4 pb-8 pt-[60px] md:ml-[220px] md:px-6 lg:px-8">
        <div className="mx-auto max-w-[1480px] space-y-4 py-4">
          <section data-mobile-section="portfolio-summary" className="panel panel-bento" style={{ padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
              <div>
                <div className="panel-header">Portfolio · operating console</div>
                <h1 style={{ fontSize: 30, lineHeight: 1, fontWeight: 400, color: 'var(--fg-0)', marginTop: 10 }}>
                  Personal treasury review
                </h1>
                <p style={{ marginTop: 12, maxWidth: 760, fontSize: 13, lineHeight: 1.7, color: 'var(--fg-2)' }}>
                  A calmer detail layer for grouped review, notes, recent execution context, and quick jumps into important holdings.
                </p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <button
                  type="button"
                  className="btn-ghost md:hidden opacity-60"
                  aria-label="Portfolio filters unavailable"
                  aria-disabled="true"
                  disabled
                  title="Portfolio filters are not available yet"
                >
                  Filters unavailable
                </button>
                <div className="panel-header">Net asset value</div>
                <div style={{ marginTop: 10, fontSize: 32, fontWeight: 300, color: 'var(--fg-0)' }}>
                  {summary ? fmtUsd(summary.total_value_usd, 2) : '—'}
                </div>
                <div style={{ marginTop: 8, fontFamily: 'var(--font-geist-mono)', fontSize: 11, color: tone(summary?.total_pnl_usd) }}>
                  {summary ? `${fmtUsd(summary.total_pnl_usd, 2)} · ${fmtPct(summary.total_pnl_pct)}` : 'Loading'}
                </div>
              </div>
            </div>
            {error ? (
              <div style={{ marginTop: 16, border: '1px solid rgba(201,119,102,0.28)', color: 'var(--pl-dn)', padding: '12px 14px' }}>
                {error}
              </div>
            ) : null}
          </section>

          <section data-mobile-section="portfolio-health" className="grid gap-3 lg:grid-cols-6">
            {[
              {
                label: 'Realized P&L',
                value: fmtUsd(performanceSummary?.combined?.realized_pnl_usd, 2),
                sub: 'Closed gains & losses',
                color: tone(performanceSummary?.combined?.realized_pnl_usd),
              },
              {
                label: 'Unrealized',
                value: fmtUsd(performanceSummary?.combined?.unrealized_pnl_usd, 2),
                sub: 'Open mark-to-market',
                color: tone(performanceSummary?.combined?.unrealized_pnl_usd),
              },
              {
                label: 'Cost basis',
                value: fmtUsd(summary?.total_cost_usd, 2),
                sub: 'Across all open holdings',
                color: 'var(--fg-0)',
              },
              {
                label: 'Open positions',
                value: String(summary?.holding_count ?? '—'),
                sub: 'Tracked assets',
                color: 'var(--fg-0)',
              },
              {
                label: 'Pending orders',
                value: String(pendingOrders.length),
                sub: pendingOrders.length > 0 ? 'Requires attention' : 'No queued orders',
                color: pendingOrders.length > 0 ? 'var(--warn)' : 'var(--fg-0)',
              },
              {
                label: 'Sync health',
                value: String(syncStatuses.filter(s => !s.degraded).length),
                sub: `${syncStatuses.length} connected sources`,
                color: syncStatuses.some(s => s.degraded) ? 'var(--warn)' : 'var(--fg-0)',
              },
            ].map(card => (
              <div key={card.label} className="panel" style={{ padding: 16 }}>
                <div className="panel-header">{card.label}</div>
                <div style={{ marginTop: 10, fontSize: 22, fontWeight: 300, color: card.color }}>{card.value}</div>
                <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--fg-3)' }}>{card.sub}</div>
              </div>
            ))}
          </section>

          <section data-mobile-section="portfolio-holdings" className="grid gap-4 xl:grid-cols-[1.45fr_0.75fr]">
            <div className="panel" style={{ padding: 0 }}>
              <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 12 }}>
                <span className="panel-header">Grouped review</span>
                <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
                  grouped by asset class
                </span>
              </div>
              {loading ? (
                <div style={{ padding: 20, color: 'var(--fg-3)' }}>Loading review groups…</div>
              ) : (
                groupedHoldings.map(group => (
                  <div key={group.name} style={{ borderBottom: '1px solid var(--line-1)' }}>
                    <div
                      className="mobile-review-card"
                      style={{
                        gap: 12,
                        alignItems: 'center',
                        padding: '14px 20px',
                        background: 'var(--bg-inset)',
                      }}
                    >
                      <div>
                        <div style={{ fontSize: 13, color: 'var(--fg-0)', textTransform: 'capitalize' }}>{group.name}</div>
                        <div style={{ marginTop: 4, fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
                          {group.holdings.length} position{group.holdings.length !== 1 ? 's' : ''}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right', fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-1)', fontSize: 11.5 }}>
                        {fmtUsd(group.value, 0)}
                      </div>
                      <div style={{ textAlign: 'right', fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-1)', fontSize: 11.5 }}>
                        {group.weightPct.toFixed(1)}%
                      </div>
                      <div style={{ textAlign: 'right', fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-3)', fontSize: 10.5 }}>
                        review
                      </div>
                    </div>
                    {group.holdings.slice(0, 3).map(holding => (
                      <Link
                        className="mobile-review-card"
                        key={`${holding.symbol}-${holding.institution}`}
                        href={`/holdings/${encodeURIComponent(holding.symbol)}?institution=${encodeURIComponent(holding.institution)}`}
                        style={{
                          display: 'grid',
                          gridTemplateColumns: '1.4fr 0.8fr 0.8fr 0.8fr',
                          gap: 12,
                          alignItems: 'center',
                          padding: '11px 20px',
                          borderTop: '1px solid var(--line-1)',
                          textDecoration: 'none',
                          color: 'inherit',
                        }}
                      >
                        <div>
                          <div style={{ fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-0)', fontSize: 12 }}>{holding.symbol}</div>
                          <div style={{ marginTop: 2, fontSize: 11, color: 'var(--fg-3)' }}>{holding.institution}</div>
                        </div>
                        <div style={{ textAlign: 'right', fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-1)', fontSize: 11.5 }}>
                          {fmtUsd(holding.current_value_usd, 0)}
                        </div>
                        <div style={{ textAlign: 'right', fontFamily: 'var(--font-geist-mono)', color: tone(holding.unrealized_pnl_pct), fontSize: 11.5 }}>
                          {fmtPct(holding.unrealized_pnl_pct)}
                        </div>
                        <div style={{ textAlign: 'right', fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-3)', fontSize: 10.5 }}>
                          open →
                        </div>
                      </Link>
                    ))}
                  </div>
                ))
              )}
            </div>

            <div className="panel" style={{ padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <div className="panel-header">Important holdings</div>
                <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>quick jump</span>
              </div>
              <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {topHoldings.map(holding => (
                  <Link
                    key={`${holding.symbol}-${holding.institution}`}
                    href={`/holdings/${encodeURIComponent(holding.symbol)}?institution=${encodeURIComponent(holding.institution)}`}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '56px 1fr auto',
                      gap: 12,
                      alignItems: 'center',
                      textDecoration: 'none',
                      color: 'inherit',
                      borderTop: '1px solid var(--line-1)',
                      paddingTop: 10,
                    }}
                  >
                    <span style={{ fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-0)', fontSize: 12 }}>{holding.symbol}</span>
                    <div>
                      <div style={{ fontSize: 11.5, color: 'var(--fg-2)' }}>{holding.institution}</div>
                      <div style={{ marginTop: 2, fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: tone(holding.unrealized_pnl_pct) }}>
                        {fmtPct(holding.unrealized_pnl_pct)}
                      </div>
                    </div>
                    <span style={{ fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-3)', fontSize: 10.5 }}>open →</span>
                  </Link>
                ))}
              </div>
            </div>
          </section>

          <div data-portfolio-workflow className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <section data-mobile-section="portfolio-action-surfaces">
              <NotePanel entityType="portfolio" entityId="portfolio" title="Portfolio notes" />

              <div style={{ marginTop: 16 }}>
                <WatchlistTeaser />
              </div>
            </section>

            <section data-mobile-section="portfolio-activity" className="panel" style={{ padding: 20 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <div className="panel-header">Recent activity</div>
                  <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>last 8 events</span>
                </div>
                <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {activityEvents.length === 0 ? (
                    <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>No intelligence activity yet.</div>
                  ) : (
                    activityEvents.map(event => (
                      <div key={event.id} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                          <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
                            {new Date(event.created_at).toISOString().slice(0, 16).replace('T', ' ')}
                          </span>
                          <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-0)' }}>
                            {event.source}
                          </span>
                          <span style={{ fontSize: 11.5, color: 'var(--fg-2)' }}>{event.status}</span>
                        </div>
                        <div style={{ marginTop: 4, fontSize: 11.5, color: 'var(--fg-3)' }}>
                          {event.message}
                        </div>
                      </div>
                    ))
                  )}
                  {recentTransactions.length > 0 ? (
                    <div style={{ borderTop: '1px solid var(--line-1)', paddingTop: 12 }}>
                      <div className="panel-header">Recent transactions</div>
                      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {recentTransactions.map(tx => (
                          <div key={tx.id} style={{ fontSize: 11.5, color: 'var(--fg-3)' }}>
                            <span style={{ fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-0)' }}>{tx.asset}</span> · {tx.type.replace(/_/g, ' ')} · {tx.total_usd != null ? fmtUsd(tx.total_usd, 2) : 'No notional'}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
            </section>
          </div>

        </div>
      </main>
    </div>
  )
}
