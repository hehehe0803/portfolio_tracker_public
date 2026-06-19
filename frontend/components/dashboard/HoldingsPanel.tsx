import Link from 'next/link'
import { type Holding } from '@/lib/api'

function fmtUsd(n: number | null | undefined, dec = 2) {
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

function fmtQty(n: number) {
  if (n < 0.001) return n.toExponential(2)
  if (n < 1) return n.toFixed(4)
  if (n < 100) return n.toFixed(2)
  return n.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

function assetTag(assetType: string) {
  const map: Record<string, { label: string; color: string; bg: string; border: string }> = {
    crypto:     { label: 'crypto',    color: 'var(--pl-up)',  bg: 'var(--pl-up-bg)',  border: 'rgba(127,179,128,0.2)' },
    stablecoin: { label: 'stable',    color: 'var(--fg-2)',   bg: 'transparent',      border: 'var(--line-2)' },
    equity:     { label: 'equity',    color: 'var(--warn)',   bg: 'var(--warn-bg)',   border: 'rgba(201,152,102,0.2)' },
    etf:        { label: 'etf',       color: 'var(--fg-1)',   bg: 'transparent',      border: 'var(--line-2)' },
  }
  return map[assetType] ?? { label: assetType, color: 'var(--fg-3)', bg: 'transparent', border: 'var(--line-1)' }
}

function freshnessText(h: Holding) {
  const freshness = h.freshness
  if (!freshness) return 'missing freshness metadata'
  const warning = freshness.warnings[0]
  if (freshness.degraded || freshness.stale || warning) return warning ?? `${freshness.source} degraded`
  return `fresh · ${freshness.source}`
}

function freshnessColor(h: Holding) {
  const freshness = h.freshness
  return !freshness || freshness.degraded || freshness.stale || freshness.warnings.length > 0
    ? 'var(--warn)'
    : 'var(--fg-3)'
}

interface HoldingsPanelProps {
  holdings: Holding[]
}

export function HoldingsPanel({ holdings }: HoldingsPanelProps) {
  const total = holdings.reduce((s, h) => s + (h.current_value_usd ?? 0), 0) || 1

  return (
    <div className="panel" style={{ padding: 0 }}>
      {/* header */}
      <div
        style={{
          padding: '14px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          borderBottom: '1px solid var(--line-1)',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-geist-mono)',
            fontSize: 10.5,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: 'var(--fg-1)',
          }}
        >
          Holdings
        </span>
        <span
          style={{
            fontFamily: 'var(--font-geist-mono)',
            fontSize: 10.5,
            color: 'var(--fg-3)',
          }}
        >
          {holdings.length} position{holdings.length !== 1 ? 's' : ''}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
          {fmtUsd(total, 0)}
        </span>
      </div>

      {/* column headers */}
      {holdings.length > 0 && (
        <div
          className="mobile-holding-columns"
          style={{
            borderBottom: '1px solid var(--line-1)',
            fontFamily: 'var(--font-geist-mono)',
            fontSize: 10,
            color: 'var(--fg-3)',
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
          }}
        >
          <span>Asset</span>
          <span style={{ textAlign: 'right' }}>Qty</span>
          <span style={{ textAlign: 'right' }}>Price</span>
          <span style={{ textAlign: 'right' }}>Alloc</span>
          <span style={{ textAlign: 'right' }}>P&amp;L</span>
          <span style={{ textAlign: 'right' }}>Value</span>
        </div>
      )}

      {/* rows */}
      <div style={{ maxHeight: 460, overflowY: 'auto' }}>
        {holdings.length === 0 ? (
          <div style={{ padding: '24px 20px', fontSize: 13, color: 'var(--fg-3)' }}>
            No holdings yet. Sync Binance or import a broker statement.
          </div>
        ) : (
          holdings
            .slice()
            .sort((a, b) => (b.current_value_usd ?? 0) - (a.current_value_usd ?? 0))
            .map(h => {
              const alloc = ((h.current_value_usd ?? 0) / total) * 100
              const pnlPos = (h.unrealized_pnl_pct ?? 0) >= 0
              const tag = assetTag(h.asset_type)

              return (
                <Link
                  key={`${h.symbol}-${h.institution}`}
                  href={`/holdings/${encodeURIComponent(h.symbol)}?institution=${encodeURIComponent(h.institution)}`}
                  style={{ textDecoration: 'none', color: 'inherit', display: 'block' }}
                >
                  <div
                    className="mobile-holding-card hover:bg-[var(--bg-2)]"
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1.4fr 1fr 0.9fr 0.85fr 0.85fr 0.75fr',
                      padding: '11px 20px',
                      borderBottom: '1px solid var(--line-1)',
                      alignItems: 'center',
                      cursor: 'pointer',
                    }}
                  >
                    {/* asset identity */}
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                        <span
                          style={{
                            fontFamily: 'var(--font-geist-mono)',
                            fontSize: 12.5,
                            color: 'var(--fg-0)',
                            letterSpacing: '0.02em',
                            minWidth: 40,
                          }}
                        >
                          {h.symbol}
                        </span>
                        <span style={{ fontSize: 11.5, color: 'var(--fg-2)' }}>{h.institution}</span>
                      </div>
                      <div style={{ display: 'flex', gap: 4, marginTop: 5 }}>
                        <span
                          style={{
                            fontSize: 9.5,
                            color: tag.color,
                            padding: '1.5px 5px',
                            border: `1px solid ${tag.border}`,
                            background: tag.bg,
                            fontFamily: 'var(--font-geist-mono)',
                            letterSpacing: '0.08em',
                            textTransform: 'uppercase',
                          }}
                        >
                          {tag.label}
                        </span>
                      </div>
                    </div>

                    {/* qty */}
                    <span
                      style={{
                        fontFamily: 'var(--font-geist-mono)',
                        fontSize: 12,
                        color: 'var(--fg-1)',
                        textAlign: 'right',
                      }}
                    >
                      {fmtQty(h.quantity)}
                    </span>

                    {/* price */}
                    <span
                      style={{
                        fontFamily: 'var(--font-geist-mono)',
                        fontSize: 12,
                        color: 'var(--fg-1)',
                        textAlign: 'right',
                      }}
                    >
                      {fmtUsd(h.current_price_usd)}
                    </span>

                    {/* alloc */}
                    <div style={{ textAlign: 'right' }}>
                      <div
                        style={{
                          fontFamily: 'var(--font-geist-mono)',
                          fontSize: 12,
                          color: 'var(--fg-0)',
                        }}
                      >
                        {alloc.toFixed(1)}%
                      </div>
                      <div
                        style={{
                          marginTop: 3,
                          height: 2,
                          background: 'var(--line-1)',
                          marginLeft: 'auto',
                          width: 48,
                          position: 'relative',
                        }}
                      >
                        <div
                          style={{
                            position: 'absolute',
                            left: 0,
                            top: 0,
                            bottom: 0,
                            width: `${Math.min(100, alloc * 2.5)}%`,
                            background: 'var(--fg-2)',
                            opacity: 0.6,
                          }}
                        />
                      </div>
                    </div>

                    {/* p&l */}
                    <div style={{ textAlign: 'right' }}>
                      <div
                        style={{
                          fontFamily: 'var(--font-geist-mono)',
                          fontSize: 12,
                          color: pnlPos ? 'var(--pl-up)' : 'var(--pl-dn)',
                        }}
                      >
                        {fmtPct(h.unrealized_pnl_pct)}
                      </div>
                      <div
                        style={{
                          fontFamily: 'var(--font-geist-mono)',
                          fontSize: 10.5,
                          color: pnlPos ? 'var(--pl-up)' : 'var(--pl-dn)',
                          opacity: 0.7,
                        }}
                      >
                        {h.unrealized_pnl_usd != null
                          ? (h.unrealized_pnl_usd >= 0 ? '+' : '') +
                            fmtUsd(h.unrealized_pnl_usd, 0)
                          : '—'}
                      </div>
                    </div>

                    {/* value */}
                    <span
                      aria-label={
                        h.current_value_usd == null
                          ? `${h.symbol} current value unavailable: ${freshnessText(h)}`
                          : `${h.symbol} current value ${fmtUsd(h.current_value_usd, 0)}: ${freshnessText(h)}`
                      }
                      style={{
                        fontFamily: 'var(--font-geist-mono)',
                        fontSize: 12,
                        color: 'var(--fg-1)',
                        textAlign: 'right',
                      }}
                    >
                      <span>{fmtUsd(h.current_value_usd, 0)}</span>
                      <span
                        style={{
                          display: 'block',
                          marginTop: 3,
                          fontSize: 9.5,
                          color: freshnessColor(h),
                        }}
                      >
                        {freshnessText(h)}
                      </span>
                    </span>
                  </div>
                </Link>
              )
            })
        )}
      </div>
    </div>
  )
}
