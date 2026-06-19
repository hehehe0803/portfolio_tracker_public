'use client'

import { useState } from 'react'
import {
  AreaChart, Area, XAxis, Line,
  Tooltip, ResponsiveContainer,
} from 'recharts'
import { type CapitalTruthSummary, type Holding, type Transaction } from '@/lib/api'

type DataPoint = { date: string; value: number; netCapitalIn?: number }
type Range = 'ALL' | 'YTD' | '1Y' | '3M' | '1M'
type AdjustedTransaction = Transaction & { adjustedQuantity: number }

type QuantityDelta = Map<string, number>

function accumulateDelta(delta: QuantityDelta, asset: string | undefined, quantity: number) {
  if (!asset || !Number.isFinite(quantity) || quantity === 0) return
  delta.set(asset, (delta.get(asset) ?? 0) + quantity)
}

function transactionQuantityDelta(tx: AdjustedTransaction): QuantityDelta {
  const delta: QuantityDelta = new Map()
  const type = tx.type.toLowerCase()
  const rawData = tx.raw_data ?? {}

  if (type.includes('split')) {
    return delta
  }

  if (type === 'staking_subscribe' || type === 'earn_subscribe') {
    const sourceAsset = String(
      rawData.stake_asset ?? rawData.from_account_asset ?? rawData.coin ?? ''
    ).toUpperCase()
    const sourceAmount = Number(rawData.stake_amount ?? rawData.amount ?? rawData.subscription_amount ?? 0)
    accumulateDelta(delta, sourceAsset, -sourceAmount)
    accumulateDelta(delta, tx.asset, tx.adjustedQuantity)
    return delta
  }

  if (type === 'staking_redeem' || type === 'earn_redeem') {
    const sourceAsset = String(rawData.redeem_asset ?? rawData.coin ?? tx.asset ?? '').toUpperCase()
    const sourceAmount = Number(
      rawData.redeem_amount ?? rawData.principal_redeemed ?? tx.adjustedQuantity
    )
    accumulateDelta(delta, sourceAsset, -sourceAmount)
    accumulateDelta(delta, tx.asset, tx.adjustedQuantity)
    return delta
  }

  if (
    type.includes('buy') ||
    type.includes('deposit') ||
    type.includes('snapshot') ||
    type.includes('reward') ||
    type.includes('airdrop') ||
    type.includes('dividend')
  ) {
    accumulateDelta(delta, tx.asset, tx.adjustedQuantity)
    return delta
  }

  if (type.includes('sell') || type.includes('withdrawal')) {
    accumulateDelta(delta, tx.asset, -tx.adjustedQuantity)
    return delta
  }

  return delta
}

function capitalFlowDelta(tx: Transaction): number {
  const type = tx.type.toLowerCase()
  const value = Math.abs(tx.total_usd ?? 0)
  if (!Number.isFinite(value) || value === 0) return 0
  if (type === 'deposit' || type === 'external_deposit' || type.includes('cash_deposit')) return value
  if (type === 'withdrawal' || type === 'external_withdrawal' || type.includes('cash_withdrawal')) return -value
  return 0
}

export function reconstructPortfolioHistory(
  holdings: Holding[],
  transactions: Transaction[],
): DataPoint[] {
  const priceMap = new Map<string, number>()
  for (const h of holdings) {
    if (h.current_price_usd != null) {
      priceMap.set(h.symbol, h.current_price_usd)
    }
  }

  const sorted = [...transactions].sort((a, b) => {
    const ts = new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    if (ts !== 0) return ts
    return a.id - b.id
  })

  const futureSplitMultiplier = new Map<string, number>()
  const adjusted: AdjustedTransaction[] = []
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    const tx = sorted[i]
    const type = tx.type.toLowerCase()
    const multiplier = futureSplitMultiplier.get(tx.asset) ?? 1

    adjusted.unshift({
      ...tx,
      adjustedQuantity: type.includes('split') ? tx.quantity : tx.quantity * multiplier,
    })

    if (type.includes('split')) {
      futureSplitMultiplier.set(tx.asset, multiplier * tx.quantity)
    }
  }

  const byDay = new Map<string, AdjustedTransaction[]>()
  for (const tx of adjusted) {
    const day = tx.timestamp.slice(0, 10)
    if (!byDay.has(day)) byDay.set(day, [])
    byDay.get(day)!.push(tx)
  }

  const qty = new Map<string, number>()
  const points: DataPoint[] = []

  const days = [...byDay.keys()].sort()
  for (const day of days) {
    for (const tx of byDay.get(day)!) {
      for (const [asset, change] of transactionQuantityDelta(tx)) {
        qty.set(asset, Math.max(0, (qty.get(asset) ?? 0) + change))
      }
    }

    let value = 0
    for (const [symbol, q] of qty) {
      const price = priceMap.get(symbol)
      if (price != null) value += q * price
    }
    if (value > 0) points.push({ date: day, value: Math.round(value * 100) / 100 })
  }

  return points
}

export function withCapitalReference(
  points: DataPoint[],
  transactions: Transaction[],
  capitalTruth: CapitalTruthSummary | null,
): DataPoint[] {
  if (!capitalTruth) return points
  const flowsByDay = new Map<string, number>()
  for (const tx of transactions) {
    const flow = capitalFlowDelta(tx)
    if (flow === 0) continue
    const day = tx.timestamp.slice(0, 10)
    flowsByDay.set(day, (flowsByDay.get(day) ?? 0) + flow)
  }

  if (flowsByDay.size === 0) {
    return points.map(point => ({ ...point, netCapitalIn: capitalTruth.net_capital_in_usd }))
  }

  let cumulative = 0
  return points.map(point => {
    cumulative += flowsByDay.get(point.date) ?? 0
    return {
      ...point,
      netCapitalIn: Math.round((cumulative || capitalTruth.net_capital_in_usd) * 100) / 100,
    }
  })
}

function filterByRange(points: DataPoint[], range: Range): DataPoint[] {
  if (range === 'ALL') return points
  const now = new Date()
  const cutoff = new Date(now)
  if (range === 'YTD') cutoff.setMonth(0, 1)
  else if (range === '1Y') cutoff.setFullYear(now.getFullYear() - 1)
  else if (range === '3M') cutoff.setMonth(now.getMonth() - 3)
  else if (range === '1M') cutoff.setMonth(now.getMonth() - 1)
  const cutoffStr = cutoff.toISOString().slice(0, 10)
  const filtered = points.filter(p => p.date >= cutoffStr)
  if (filtered.length === 0 && points.length > 0) {
    return [points[points.length - 1]]
  }
  return filtered
}

function fmtDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function fmtCurrency(v: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', maximumFractionDigits: 0,
  }).format(v)
}

function fmtCompact(n: number | null | undefined, signed = true) {
  if (n == null) return '—'
  const abs = Math.abs(n)
  const sign = signed ? (n < 0 ? '-' : n > 0 ? '+' : '') : (n < 0 ? '-' : '')
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`
  return `${sign}$${abs.toFixed(2)}`
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

interface PortfolioChartProps {
  holdings: Holding[]
  transactions: Transaction[]
  capitalTruth?: CapitalTruthSummary | null
}

export function PortfolioChart({ holdings, transactions, capitalTruth = null }: PortfolioChartProps) {
  const [range, setRange] = useState<Range>('ALL')

  const reconstructedPoints = reconstructPortfolioHistory(holdings, transactions)
  const allPoints = withCapitalReference(
    reconstructedPoints.length > 0 || !capitalTruth
      ? reconstructedPoints
      : [{
          date: new Date().toISOString().slice(0, 10),
          value: capitalTruth.current_value_usd,
        }],
    transactions,
    capitalTruth,
  )
  const points = filterByRange(allPoints, range)
  const noDataInRange = allPoints.length > 0 && points.length === 1 && range !== 'ALL'

  const first = points[0]?.value
  const last = points[points.length - 1]?.value
  const change = first != null && last != null ? ((last - first) / first) * 100 : null
  const currentValue = capitalTruth?.current_value_usd ?? last
  const lifetimePnl = capitalTruth?.lifetime_pnl_usd ?? null
  const lifetimePnlPos = (lifetimePnl ?? 0) >= 0

  if (allPoints.length === 0) {
    return (
      <div className="panel panel-bento p-5">
        <p className="panel-header">Capital truth</p>
        <h3 className="panel-title mt-2">Portfolio growth</h3>
        <p className="mt-6 text-sm text-dim">
          No historical series yet. Sync Binance or import XTB transactions to see the curve.
        </p>
      </div>
    )
  }

  return (
    <div className="panel panel-bento" style={{ padding: 22 }}>
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div style={{ minWidth: 260 }}>
          <p className="panel-header">Capital truth</p>
          <h3 className="panel-title mt-2">Portfolio growth</h3>
          <div style={{ marginTop: 12, fontSize: 52, fontWeight: 300, letterSpacing: '-0.055em', lineHeight: 0.95, color: 'var(--fg-0)' }}>
            {fmtCurrency(currentValue ?? 0)}
          </div>
          <div style={{ marginTop: 14, display: 'flex', flexWrap: 'wrap', gap: 12 }}>
            <TruthStat label="Lifetime P/L" value={fmtCompact(lifetimePnl)} tone={lifetimePnlPos ? 'up' : 'dn'} />
            <TruthStat label="Lifetime return" value={fmtPct(capitalTruth?.lifetime_return_pct)} tone={lifetimePnlPos ? 'up' : 'dn'} />
            <TruthStat label="Net capital in" value={fmtCompact(capitalTruth?.net_capital_in_usd, false)} />
          </div>
          <p className="panel-subtitle mt-4 max-w-xl">
            Deposits - withdrawals vs current value. Excludes rows flagged incomplete.
          </p>
          {capitalTruth?.warnings?.length ? (
            <div className="mt-3 text-xs" style={{ color: 'var(--warn)', fontFamily: 'var(--font-geist-mono)' }}>
              {capitalTruth.warnings[0]}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2">
          {(['ALL', 'YTD', '1Y', '3M', '1M'] as Range[]).map(r => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={range === r ? 'btn-primary !px-4 !py-3' : 'btn-ghost !px-4 !py-3'}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_260px]">
        <div className="surface-row p-4">
          <div style={{ height: 310 }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
              <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="portfolioGrowthFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#9bf56a" stopOpacity={0.22} />
                    <stop offset="100%" stopColor="#9bf56a" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  tickFormatter={fmtDate}
                  interval="preserveStartEnd"
                  tick={{ fontSize: 10, fill: 'rgba(148,163,154,0.8)', fontFamily: 'var(--font-geist-mono), monospace' }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  formatter={(value, name) => [fmtCurrency(Number(value ?? 0)), name === 'netCapitalIn' ? 'Net capital in' : 'Portfolio value'] as const}
                  labelFormatter={(label) => fmtDate(String(label ?? ''))}
                  contentStyle={{
                    background: '#11161a',
                    border: '1px solid rgba(155,245,106,0.18)',
                    borderRadius: '14px',
                    fontFamily: 'var(--font-geist-mono), monospace',
                    fontSize: 11,
                  }}
                  labelStyle={{ color: '#9bf56a' }}
                  itemStyle={{ color: '#dae4de' }}
                />
                <Line
                  type="monotone"
                  dataKey="netCapitalIn"
                  stroke="rgba(218,228,222,0.46)"
                  strokeWidth={1.5}
                  strokeDasharray="6 6"
                  dot={false}
                  activeDot={false}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="rgba(115,230,255,0.18)"
                  strokeWidth={6}
                  dot={false}
                  activeDot={false}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#9bf56a"
                  strokeWidth={2.2}
                  fill="url(#portfolioGrowthFill)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="space-y-4">
          <div className="surface-row p-4">
            <div className="metric-label">Current range</div>
            <div className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-bright">{range}</div>
          </div>
          <div className="surface-row p-4">
            <div className="metric-label">Start → end</div>
            <div className="mt-2 font-mono text-sm text-bright">
              {`${fmtCurrency(first ?? 0)} → ${fmtCurrency(last ?? 0)}`}
            </div>
            {change != null && !noDataInRange ? (
              <div className={`mt-2 text-sm ${change >= 0 ? 'val-pos' : 'val-neg'}`}>
                {change >= 0 ? '+' : ''}{change.toFixed(1)}%
              </div>
            ) : null}
          </div>
          <div className="surface-row p-4">
            <div className="metric-label">Reference line</div>
            <p className="mt-2 text-sm text-dim">
              Dashed line shows cumulative net capital in. The gap is lifetime P/L.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function TruthStat({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'dn' }) {
  const color = tone === 'up' ? 'var(--pl-up)' : tone === 'dn' ? 'var(--pl-dn)' : 'var(--fg-1)'
  return (
    <div style={{ minWidth: 128, padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line-1)' }}>
      <div className="panel-header" style={{ marginBottom: 5 }}>{label}</div>
      <div style={{ color, fontFamily: 'var(--font-geist-mono)', fontSize: 14, letterSpacing: '-0.01em' }}>{value}</div>
    </div>
  )
}
