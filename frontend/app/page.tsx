'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { useAuth } from '@/components/providers/auth-provider'
import {
  portfolioAPI,
  syncAPI,
  type AssetContributionSummary,
  type CapitalTruthSummary,
  type PendingOrder,
  type PerformanceSummary,
  type PortfolioSummary,
  type SyncStatus,
  type Transaction,
} from '@/lib/api'
import { HoldingsPanel } from '@/components/dashboard/HoldingsPanel'
import { AllocationPanel } from '@/components/dashboard/AllocationPanel'
import { ActivityFeed } from '@/components/dashboard/ActivityFeed'
import { PortfolioChart } from '@/components/dashboard/PortfolioChart'
import { PerformanceSummaryPanel } from '@/components/dashboard/PerformanceSummaryPanel'
import { PendingOrdersPanel } from '@/components/dashboard/PendingOrdersPanel'
import { SyncStatusPanel } from '@/components/dashboard/SyncStatusPanel'
import { WatchlistTeaser } from '@/components/intelligence/WatchlistTeaser'

type OptionalDataState = 'ready' | 'unavailable'

function fmtUsd(n: number | null | undefined, dec = 0) {
  if (n == null) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD',
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  }).format(n)
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

function fmtCompact(n: number | null | undefined) {
  if (n == null) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : n > 0 ? '+' : ''
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`
  return `${sign}$${abs.toFixed(2)}`
}

const RECENT_TRANSACTION_LIMIT = 50

async function loadRecentTransactions(): Promise<Transaction[]> {
  return portfolioAPI.transactions({ limit: RECENT_TRANSACTION_LIMIT, offset: 0 })
}

// ── Thin flash strip ──────────────────────────────────────────────────────────
function FlashStrip({
  syncStatuses,
  pendingOrders,
  summary,
}: {
  syncStatuses: SyncStatus[]
  pendingOrders: PendingOrder[]
  summary: PortfolioSummary | null
}) {
  const items: { tag: string; text: string; tone: 'wrn' | 'up' | 'dn' | null }[] = []

  const degraded = syncStatuses.filter(s => s.degraded)
  if (degraded.length > 0) {
    items.push({ tag: 'SYNC', text: `${degraded.map(s => s.name).join(', ')} degraded`, tone: 'wrn' })
  }
  if (pendingOrders.length > 0) {
    items.push({ tag: 'ORDERS', text: `${pendingOrders.length} open limit order${pendingOrders.length > 1 ? 's' : ''}`, tone: null })
  }
  if (summary) {
    const top = [...summary.holdings]
      .sort((a, b) => (b.current_value_usd ?? 0) - (a.current_value_usd ?? 0))
      .slice(0, 2)
    for (const h of top) {
      const pct = h.unrealized_pnl_pct
      if (pct != null) {
        items.push({
          tag: h.symbol,
          text: `${fmtCompact(h.current_value_usd)} · ${fmtPct(pct)}`,
          tone: pct >= 0 ? 'up' : 'dn',
        })
      }
    }
  }

  if (items.length === 0) return null

  return (
    <div
      style={{
        height: 34,
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        background: 'var(--bg-1)',
        border: '1px solid var(--line-1)',
        borderRadius: 'var(--radius)',
        overflow: 'hidden',
        padding: '0 14px',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-geist-mono)',
          fontSize: 9.5,
          color: 'var(--fg-3)',
          letterSpacing: '0.2em',
          paddingRight: 14,
          borderRight: '1px solid var(--line-1)',
          flexShrink: 0,
        }}
      >
        LIVE
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, paddingLeft: 14, overflow: 'hidden' }}>
        {items.map((it, i) => (
          <span
            key={i}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 10,
              paddingRight: 24,
              whiteSpace: 'nowrap',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-geist-mono)',
                fontSize: 9.5,
                letterSpacing: '0.16em',
                padding: '2px 5px',
                color:
                  it.tone === 'wrn' ? 'var(--warn)'
                  : it.tone === 'up' ? 'var(--pl-up)'
                  : it.tone === 'dn' ? 'var(--pl-dn)'
                  : 'var(--fg-3)',
                border: `1px solid ${
                  it.tone === 'wrn' ? 'rgba(201,152,102,0.28)'
                  : it.tone === 'up' ? 'rgba(127,179,128,0.25)'
                  : it.tone === 'dn' ? 'rgba(201,119,102,0.25)'
                  : 'var(--line-2)'
                }`,
              }}
            >
              {it.tag}
            </span>
            <span style={{ fontSize: 11.5, color: 'var(--fg-1)' }}>{it.text}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

// ── Row 1 — Command summary ───────────────────────────────────────────────────
function Row1Summary({
  summary,
  performanceSummary,
  syncStatuses,
  onSync,
  syncing,
}: {
  summary: PortfolioSummary
  performanceSummary: PerformanceSummary | null
  syncStatuses: SyncStatus[]
  onSync: () => void
  syncing: boolean
}) {
  const pnlPos = (summary.total_pnl_usd ?? 0) >= 0
  const realized = performanceSummary?.combined?.realized_pnl_usd
  const unrealized = performanceSummary?.combined?.unrealized_pnl_usd
  const totalPnl = performanceSummary?.combined?.total_pnl_usd ?? summary.total_pnl_usd
  const allHealthy = syncStatuses.length > 0 && syncStatuses.every(s => !s.degraded)
  const anyDegraded = syncStatuses.some(s => s.degraded)
  const binanceSync = syncStatuses.find(s => s.name === 'binance')

  return (
    <section
      data-mobile-section="overview-summary"
      className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1.5fr_1.1fr_1fr_1fr]"
      style={{ alignItems: 'stretch' }}
    >
      {/* Total portfolio value — hero */}
      <div className="panel panel-bento" style={{ padding: 22, position: 'relative' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span className="panel-header">Total portfolio value</span>
          <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 9.5, color: 'var(--fg-3)', letterSpacing: '0.12em' }}>
            USD · MARK-TO-MARKET
          </span>
        </div>
        <div style={{ marginTop: 14 }}>
          <div
            style={{
              fontSize: 46,
              fontWeight: 300,
              letterSpacing: '-0.04em',
              lineHeight: 0.95,
              color: 'var(--fg-0)',
            }}
          >
            <span style={{ color: 'var(--fg-3)', fontWeight: 300 }}>$</span>
            {Math.floor(summary.total_value_usd).toLocaleString('en-US')}
            <span style={{ color: 'var(--fg-3)', fontSize: 28 }}>
              .{(summary.total_value_usd % 1).toFixed(2).slice(2)}
            </span>
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            gap: 24,
            marginTop: 20,
            paddingTop: 14,
            borderTop: '1px solid var(--line-1)',
            flexWrap: 'wrap',
          }}
        >
          <MiniStat label="Positions" value={String(summary.holding_count)} />
          <MiniStat label="Cost basis" value={fmtUsd(summary.total_cost_usd)} />
          <MiniStat
            label="All-time P&L"
            value={fmtCompact(summary.total_pnl_usd)}
            tone={pnlPos ? 'up' : 'dn'}
          />
        </div>
      </div>

      {/* Total P&L */}
      <div className="panel panel-bento" style={{ padding: 20, position: 'relative' }}>
        <span className="panel-header">Total P&L</span>
        <div
          style={{
            marginTop: 12,
            fontSize: 34,
            fontWeight: 300,
            letterSpacing: '-0.035em',
            lineHeight: 1,
            color: pnlPos ? 'var(--pl-up)' : 'var(--pl-dn)',
          }}
        >
          {fmtCompact(totalPnl)}
        </div>
        <div
          style={{
            fontFamily: 'var(--font-geist-mono)',
            fontSize: 11.5,
            color: pnlPos ? 'var(--pl-up)' : 'var(--pl-dn)',
            marginTop: 6,
            letterSpacing: '0.02em',
          }}
        >
          {fmtPct(summary.total_pnl_pct)}
        </div>

        {realized != null || unrealized != null ? (
          <div style={{ marginTop: 18 }}>
            <div
              style={{
                display: 'flex',
                fontSize: 10,
                color: 'var(--fg-3)',
                marginBottom: 5,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                fontFamily: 'var(--font-geist-mono)',
              }}
            >
              <span style={{ flex: 1 }}>Realized</span>
              <span>Unrealized</span>
            </div>
            {realized != null && unrealized != null && totalPnl ? (
              <div style={{ display: 'flex', height: 4, background: 'var(--line-1)', overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${Math.max(4, (Math.abs(realized) / Math.abs(totalPnl)) * 100)}%`,
                    background: 'var(--pl-up)',
                    opacity: 0.85,
                  }}
                />
                <div
                  style={{
                    flex: 1,
                    background: 'var(--pl-up)',
                    opacity: 0.3,
                  }}
                />
              </div>
            ) : null}
            <div
              style={{
                fontFamily: 'var(--font-geist-mono)',
                display: 'flex',
                fontSize: 11.5,
                marginTop: 5,
                color: 'var(--fg-1)',
              }}
            >
              <span style={{ flex: 1 }}>{fmtCompact(realized)}</span>
              <span>{fmtCompact(unrealized)}</span>
            </div>
          </div>
        ) : null}
      </div>

      {/* XIRR / return quality */}
      <div className="panel panel-bento" style={{ padding: 20, position: 'relative' }}>
        <span className="panel-header">Return · XIRR</span>
        {performanceSummary?.combined?.xirr != null ? (
          <>
            <div
              style={{
                marginTop: 12,
                fontSize: 34,
                fontWeight: 300,
                letterSpacing: '-0.035em',
                lineHeight: 1,
                color: (performanceSummary.combined.xirr ?? 0) >= 0 ? 'var(--pl-up)' : 'var(--pl-dn)',
              }}
            >
              {((performanceSummary.combined.xirr ?? 0) * 100).toFixed(1)}
              <span style={{ fontSize: 20, color: 'var(--fg-3)' }}>%</span>
            </div>
            <div style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)', marginTop: 6, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
              annualized
            </div>
            <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <MiniStat label="Net invested" value={fmtUsd(performanceSummary.combined.net_invested_capital_usd)} />
              <MiniStat label="Fees" value={fmtUsd(performanceSummary.combined.fees_usd)} />
            </div>
          </>
        ) : (
          <div style={{ marginTop: 14, fontSize: 13, color: 'var(--fg-3)' }}>
            Performance data unavailable
          </div>
        )}
      </div>

      {/* Sync / system status */}
      <div className="panel panel-bento" style={{ padding: 20, position: 'relative' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span className="panel-header">System · Sync</span>
          {anyDegraded ? (
            <span className="badge-amber">Issue</span>
          ) : allHealthy ? (
            <span className="badge-green">Healthy</span>
          ) : (
            <span className="badge-dim">Idle</span>
          )}
        </div>
        <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 7 }}>
          {syncStatuses.map(s => (
            <div
              key={s.name}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 9,
                padding: '7px 10px',
                background: 'var(--bg-inset)',
                border: '1px solid var(--line-1)',
              }}
            >
              <span
                className={`signal-dot ${s.degraded ? 'signal-dot-amber' : ''}`}
              />
              <span style={{ fontSize: 12, color: 'var(--fg-0)', flex: 1 }}>{s.name}</span>
              <span
                style={{
                  fontFamily: 'var(--font-geist-mono)',
                  fontSize: 10,
                  color: s.degraded ? 'var(--warn)' : 'var(--fg-2)',
                  letterSpacing: '0.06em',
                }}
              >
                {s.last_sync_at
                  ? new Date(s.last_sync_at).toISOString().slice(11, 19)
                  : '—'}
              </span>
            </div>
          ))}
          {syncStatuses.length === 0 && (
            <span style={{ fontSize: 12, color: 'var(--fg-3)' }}>No sync channels configured</span>
          )}
        </div>
        <div style={{ marginTop: 16 }}>
          <button
            onClick={onSync}
            disabled={syncing}
            className="btn-ghost"
            style={{ width: '100%', fontSize: 10, letterSpacing: '0.14em' }}
          >
            {syncing ? 'Syncing…' : 'Sync Binance'}
          </button>
        </div>
        {binanceSync?.warning ? (
          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--warn)', fontFamily: 'var(--font-geist-mono)' }}>
            {binanceSync.warning}
          </div>
        ) : null}
      </div>
    </section>
  )
}

function MiniStat({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'dn' }) {
  const color = tone === 'up' ? 'var(--pl-up)' : tone === 'dn' ? 'var(--pl-dn)' : 'var(--fg-1)'
  return (
    <div>
      <div className="panel-header" style={{ marginBottom: 3 }}>{label}</div>
      <div
        style={{
          fontFamily: 'var(--font-geist-mono)',
          fontSize: 13,
          color,
          letterSpacing: '-0.01em',
        }}
      >
        {value}
      </div>
    </div>
  )
}

// ── Row 2 — Portfolio Health ──────────────────────────────────────────────────
function ConcentrationPanel({ summary }: { summary: PortfolioSummary }) {
  const total = summary.total_value_usd || 1
  const sorted = [...summary.holdings]
    .filter(h => (h.current_value_usd ?? 0) > 0)
    .sort((a, b) => (b.current_value_usd ?? 0) - (a.current_value_usd ?? 0))
    .slice(0, 6)

  const top3Weight = sorted.slice(0, 3).reduce((s, h) => s + ((h.current_value_usd ?? 0) / total) * 100, 0)

  return (
    <div className="panel" style={{ padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 16 }}>
        <span
          style={{
            fontFamily: 'var(--font-geist-mono)',
            fontSize: 10.5,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: 'var(--fg-1)',
          }}
        >
          Risk · Concentration
        </span>
        <div style={{ flex: 1 }} />
        <span className={top3Weight > 60 ? 'badge-amber' : 'badge-dim'}>
          {top3Weight > 60 ? 'Elevated' : 'Normal'}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 20, marginBottom: 18 }}>
        <div>
          <div className="panel-header" style={{ marginBottom: 4 }}>Top-3 weight</div>
          <div
            style={{
              fontSize: 26,
              fontWeight: 300,
              color: top3Weight > 60 ? 'var(--warn)' : 'var(--fg-0)',
              letterSpacing: '-0.02em',
            }}
          >
            {top3Weight.toFixed(0)}
            <span style={{ fontSize: 15, color: 'var(--fg-3)' }}>%</span>
          </div>
        </div>
        <div>
          <div className="panel-header" style={{ marginBottom: 4 }}>Positions</div>
          <div style={{ fontSize: 26, fontWeight: 300, color: 'var(--fg-0)', letterSpacing: '-0.02em' }}>
            {summary.holding_count}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {sorted.map(h => {
          const w = ((h.current_value_usd ?? 0) / total) * 100
          return (
            <div key={`${h.symbol}-${h.institution}`} style={{ marginBottom: 2 }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: 3,
                  fontSize: 11.5,
                  color: 'var(--fg-1)',
                }}
              >
                <span style={{ fontFamily: 'var(--font-geist-mono)' }}>{h.symbol}</span>
                <span style={{ fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-2)' }}>
                  {w.toFixed(1)}%
                </span>
              </div>
              <div style={{ position: 'relative', height: 3, background: 'var(--line-1)' }}>
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    width: `${Math.max(2, Math.min(100, w * 2.2))}%`,
                    background: w > 30 ? 'var(--warn)' : 'var(--fg-1)',
                    opacity: 0.6,
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function assetContributionPct(row: AssetContributionSummary['assets'][number]) {
  if (!row.total_cost_usd) return null
  return (row.net_lifetime_pnl_usd / Math.abs(row.total_cost_usd)) * 100
}

function AssetContributionPanel({
  summary,
  unavailable,
}: {
  summary: AssetContributionSummary | null
  unavailable: boolean
}) {
  const [mode, setMode] = useState<'dollars' | 'percent'>('dollars')
  const assets = summary?.assets ?? []
  const ranked = [...assets].sort((a, b) => {
    if (mode === 'percent') {
      return (assetContributionPct(b) ?? -Infinity) - (assetContributionPct(a) ?? -Infinity)
    }
    return b.net_lifetime_pnl_usd - a.net_lifetime_pnl_usd
  })
  const winners = ranked.filter(row => row.net_lifetime_pnl_usd > 0).slice(0, 4)
  const losers = [...assets]
    .filter(row => row.net_lifetime_pnl_usd < 0)
    .sort((a, b) => {
      if (mode === 'percent') {
        return (assetContributionPct(a) ?? Infinity) - (assetContributionPct(b) ?? Infinity)
      }
      return a.net_lifetime_pnl_usd - b.net_lifetime_pnl_usd
    })
    .slice(0, 4)

  return (
    <div className="panel" style={{ padding: 0 }}>
      <div
        style={{
          padding: '14px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          borderBottom: '1px solid var(--line-1)',
          flexWrap: 'wrap',
        }}
      >
        <span className="panel-header">Asset winners / losers</span>
        <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
          lifetime P/L by asset · dollars first
        </span>
        <div style={{ flex: 1 }} />
        <div style={{ display: 'inline-flex', border: '1px solid var(--line-2)' }}>
          {(['dollars', 'percent'] as const).map(option => (
            <button
              key={option}
              type="button"
              onClick={() => setMode(option)}
              aria-pressed={mode === option}
              className="btn-ghost"
              style={{
                border: 0,
                borderRadius: 0,
                padding: '6px 10px',
                color: mode === option ? 'var(--fg-0)' : 'var(--fg-3)',
                background: mode === option ? 'var(--bg-2)' : 'transparent',
              }}
            >
              {option === 'dollars' ? '$ P/L' : '% return'}
            </button>
          ))}
        </div>
      </div>

      {unavailable ? (
        <div style={{ padding: '18px 20px', fontSize: 13, color: 'var(--fg-3)' }}>
          Asset winners/losers are temporarily unavailable.
        </div>
      ) : assets.length === 0 ? (
        <div style={{ padding: '18px 20px', fontSize: 13, color: 'var(--fg-3)' }}>
          No asset contribution rows yet. Import history or sync positions to rank winners and losers.
        </div>
      ) : (
        <div className="grid gap-0 lg:grid-cols-2">
          <AssetContributionList title="Biggest winners" rows={winners} empty="No winning assets yet." />
          <AssetContributionList title="Biggest losers" rows={losers} empty="No losing assets yet." />
        </div>
      )}
    </div>
  )
}

function AssetContributionList({
  title,
  rows,
  empty,
}: {
  title: string
  rows: AssetContributionSummary['assets']
  empty: string
}) {
  return (
    <div style={{ padding: '16px 20px', borderRight: title.includes('winners') ? '1px solid var(--line-1)' : undefined }}>
      <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 12 }}>
        <span className="panel-header">{title}</span>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10, color: 'var(--fg-3)', letterSpacing: '0.12em' }}>
          NET · REALIZED · OPEN
        </span>
      </div>
      {rows.length === 0 ? (
        <div style={{ fontSize: 13, color: 'var(--fg-3)' }}>{empty}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {rows.map(row => {
            const positive = row.net_lifetime_pnl_usd >= 0
            const pct = assetContributionPct(row)
            const href = `/holdings/${encodeURIComponent(row.symbol)}?institution=${encodeURIComponent(row.institution)}`
            return (
              <Link key={`${title}-${row.symbol}-${row.institution}`} href={href} style={{ color: 'inherit', textDecoration: 'none' }}>
                <div
                  className="mobile-asset-contribution-card"
                  style={{
                    gridTemplateColumns: 'minmax(110px,1fr) minmax(120px,0.95fr) minmax(140px,1.15fr)',
                    gap: 12,
                    alignItems: 'center',
                    padding: '10px 0',
                    borderBottom: '1px solid var(--line-1)',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 12.5, color: 'var(--fg-0)' }}>
                        {row.symbol}
                      </span>
                      <span style={{ fontSize: 10, color: 'var(--fg-3)', textTransform: 'uppercase' }}>{row.asset_type}</span>
                    </div>
                    <div style={{ marginTop: 4, fontSize: 11.5, color: 'var(--fg-3)' }}>
                      {row.institution === 'multiple' ? row.institutions.join(' + ') : row.institution}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 16, color: positive ? 'var(--pl-up)' : 'var(--pl-dn)' }}>
                      {fmtCompact(row.net_lifetime_pnl_usd)}
                    </div>
                    <div style={{ marginTop: 3, fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
                      {`${pct == null ? 'pct n/a' : fmtPct(pct)} · value ${fmtUsd(row.current_value_usd, 0)}`}
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 6, fontFamily: 'var(--font-geist-mono)', fontSize: 10.5 }}>
                    <span style={{ color: row.realized_pnl_usd >= 0 ? 'var(--pl-up)' : 'var(--pl-dn)' }}>{`realized ${fmtCompact(row.realized_pnl_usd)}`}</span>
                    <span style={{ color: row.unrealized_pnl_usd >= 0 ? 'var(--pl-up)' : 'var(--pl-dn)' }}>{`open ${fmtCompact(row.unrealized_pnl_usd)}`}</span>
                    <span style={{ color: 'var(--fg-3)' }}>{`rewards ${fmtCompact(row.reward_income_usd)}`}</span>
                    <span style={{ color: 'var(--fg-3)' }}>{`fees ${fmtCompact(-Math.abs(row.fees_usd))}`}</span>
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Main dashboard page ───────────────────────────────────────────────────────
export default function DashboardPage() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [capitalTruth, setCapitalTruth] = useState<CapitalTruthSummary | null>(null)
  const [performanceSummary, setPerformanceSummary] = useState<PerformanceSummary | null>(null)
  const [assetContributions, setAssetContributions] = useState<AssetContributionSummary | null>(null)
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([])
  const [syncStatuses, setSyncStatuses] = useState<SyncStatus[]>([])
  const [assetContributionsState, setAssetContributionsState] = useState<OptionalDataState>('ready')
  const [pendingOrdersState, setPendingOrdersState] = useState<OptionalDataState>('ready')
  const [syncStatusesState, setSyncStatusesState] = useState<OptionalDataState>('ready')
  const [txs, setTxs] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [error, setError] = useState('')

  const loadBackgroundPanels = useCallback(async () => {
    const [txsR, perfR, assetR, ordersR] = await Promise.allSettled([
      loadRecentTransactions(),
      portfolioAPI.performanceSummary(),
      portfolioAPI.assetContributions({ sort_by: 'net_lifetime_pnl_usd', order: 'desc' }),
      portfolioAPI.pendingOrders(),
    ])

    setTxs(txsR.status === 'fulfilled' ? txsR.value : [])
    setPerformanceSummary(perfR.status === 'fulfilled' ? perfR.value : null)
    setAssetContributions(assetR.status === 'fulfilled' ? assetR.value : null)
    setPendingOrders(ordersR.status === 'fulfilled' ? ordersR.value : [])
    setAssetContributionsState(assetR.status === 'fulfilled' ? 'ready' : 'unavailable')
    setPendingOrdersState(ordersR.status === 'fulfilled' ? 'ready' : 'unavailable')
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    setCapitalTruth(null)
    setPerformanceSummary(null)
    setAssetContributions(null)
    setPendingOrders([])
    setTxs([])

    const [summaryR, capitalTruthR, syncR] = await Promise.allSettled([
      portfolioAPI.summary(),
      portfolioAPI.capitalTruth(),
      syncAPI.status(),
    ])

    if (summaryR.status === 'rejected') {
      const e = summaryR.reason
      setError(e instanceof Error ? e.message : 'Failed to load dashboard data')
      setSummary(null)
      setLoading(false)
      return
    }

    setSummary(summaryR.value)
    setCapitalTruth(capitalTruthR.status === 'fulfilled' ? capitalTruthR.value : null)
    setSyncStatuses(syncR.status === 'fulfilled' ? syncR.value : [])
    setSyncStatusesState(syncR.status === 'fulfilled' ? 'ready' : 'unavailable')
    setLoading(false)

    void loadBackgroundPanels()
  }, [loadBackgroundPanels])

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) { router.push('/login'); return }
    void load()
  }, [isAuthenticated, isLoading, load, router])

  async function handleSync() {
    setSyncing(true)
    setSyncMsg('')
    try {
      const r = await syncAPI.binance()
      if (r.error) {
        setSyncMsg(`Error: ${r.error}`)
      } else {
        setSyncMsg(`Synced ${r.synced} records`)
        load()
      }
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : 'Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div
          style={{
            padding: 32,
            background: 'var(--bg-1)',
            border: '1px solid var(--line-2)',
            maxWidth: 380,
            textAlign: 'center',
          }}
        >
          <span className="panel-header">Validating session</span>
          <div
            style={{ marginTop: 16, fontSize: 13, color: 'var(--fg-0)', fontWeight: 500 }}
          >
            Restoring access<span className="cursor" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen">
      <Header />
      <Sidebar />

      <main
        style={{ paddingTop: 60, paddingBottom: 40 }}
        className="md:ml-[220px]"
      >
        <div
          style={{ padding: '22px clamp(16px, 2vw, 32px) 0', maxWidth: 1600, margin: '0 auto' }}
          className="space-y-5"
        >
          {/* error banner */}
          {error ? (
            <div
              style={{
                padding: '10px 14px',
                background: 'var(--pl-dn-bg)',
                border: '1px solid rgba(201,119,102,0.25)',
                fontSize: 12.5,
                color: 'var(--pl-dn)',
                fontFamily: 'var(--font-geist-mono)',
              }}
            >
              {error}
            </div>
          ) : null}

          {/* sync feedback */}
          {syncMsg ? (
            <div
              style={{
                padding: '8px 14px',
                background: 'var(--bg-2)',
                border: '1px solid var(--line-2)',
                fontSize: 11.5,
                color: 'var(--fg-1)',
                fontFamily: 'var(--font-geist-mono)',
                letterSpacing: '0.06em',
              }}
            >
              {syncMsg}
            </div>
          ) : null}

          {loading ? (
            <LoadingSkeleton />
          ) : summary ? (
            <>
              {/* ── Row 1: Command summary ── */}
              <Row1Summary
                summary={summary}
                performanceSummary={performanceSummary}
                syncStatuses={syncStatuses}
                onSync={handleSync}
                syncing={syncing}
              />

              {/* ── Row 2: Capital truth chart ── */}
              <section data-mobile-section="overview-growth">
                <PortfolioChart holdings={summary.holdings} transactions={txs} capitalTruth={capitalTruth} />
              </section>

              {/* ── Row 3: Asset contribution truth ── */}
              <section data-mobile-section="overview-asset-contributions">
                <AssetContributionPanel
                  summary={assetContributions}
                  unavailable={assetContributionsState === 'unavailable'}
                />
              </section>

              {/* ── Row 4: Health ── */}
              <section data-mobile-section="overview-health" className="space-y-4">
                <FlashStrip
                  syncStatuses={syncStatuses}
                  pendingOrders={pendingOrders}
                  summary={summary}
                />
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[2fr_1fr_1fr]">
                  <PerformanceSummaryPanel summary={performanceSummary} />
                  <ConcentrationPanel summary={summary} />
                  <SyncStatusPanel statuses={syncStatuses} unavailable={syncStatusesState === 'unavailable'} />
                </div>
              </section>

              {/* ── Row 5: Holdings intelligence ── */}
              <section data-mobile-section="overview-holdings" className="space-y-4">
                <div className="grid gap-4 xl:grid-cols-[1.4fr_0.6fr]">
                  <HoldingsPanel holdings={summary.holdings} />
                  <AllocationPanel byAssetType={summary.by_asset_type} />
                </div>
              </section>

              {/* ── Row 6: Action surfaces and activity ── */}
              <div data-overview-workflow className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
                <section data-mobile-section="overview-action-surfaces" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <WatchlistTeaser compact />
                  <PendingOrdersPanel orders={pendingOrders} unavailable={pendingOrdersState === 'unavailable'} />
                </section>
                <section data-mobile-section="overview-activity">
                  <ActivityFeed transactions={txs} />
                </section>
              </div>
            </>
          ) : null}
        </div>
      </main>
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel panel-bento" style={{ padding: 20 }}>
        <span className="panel-header">Loading telemetry</span>
        <div style={{ marginTop: 10, fontSize: 13, color: 'var(--fg-2)' }}>
          Preparing first paint<span className="cursor" />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        {[0, 1, 2, 3].map(i => (
          <div key={i} className="panel" style={{ height: 140 }}>
            <div style={{ padding: 20 }}>
              <div style={{ height: 10, width: '50%', background: 'var(--line-2)', marginBottom: 14 }} className="animate-pulse" />
              <div style={{ height: 36, width: '70%', background: 'var(--line-1)' }} className="animate-pulse" />
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[2fr_1fr_1fr]">
        {[0, 1, 2].map(i => (
          <div key={i} className="panel" style={{ height: 200 }} />
        ))}
      </div>
    </div>
  )
}
