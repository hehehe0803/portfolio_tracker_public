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
  type DashboardContract,
  type SyncStatus,
} from '@/lib/api'

type Tone = 'up' | 'down' | 'neutral' | 'warning'
type MoneyInput = string | number | null | undefined

function numberValue(value: MoneyInput): number | null {
  if (value == null) return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatUsd(value: MoneyInput, options: { signed?: boolean; decimals?: number } = {}) {
  const amount = numberValue(value)
  if (amount == null) return 'Unavailable'

  const decimals = options.decimals ?? 2
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(amount)

  if (!options.signed || amount <= 0) return formatted
  return `+${formatted}`
}

function formatPct(value: MoneyInput, options: { signed?: boolean; decimals?: number } = {}) {
  const amount = numberValue(value)
  if (amount == null) return 'Unavailable'
  const decimals = options.decimals ?? 1
  const formatted = `${amount.toFixed(decimals)}%`
  if (!options.signed || amount <= 0) return formatted
  return `+${formatted}`
}

function toneForAmount(value: MoneyInput): Tone {
  const amount = numberValue(value)
  if (amount == null || amount === 0) return 'neutral'
  return amount > 0 ? 'up' : 'down'
}

function toneColor(tone: Tone) {
  if (tone === 'up') return 'var(--pl-up)'
  if (tone === 'down') return 'var(--pl-dn)'
  if (tone === 'warning') return 'var(--warn)'
  return 'var(--fg-0)'
}

function readableToken(value: string) {
  return value.replace(/[_-]/g, ' ')
}

function titleCase(value: string) {
  return readableToken(value).replace(/\b\w/g, char => char.toUpperCase())
}

function assetTypeLabel(value: string) {
  if (value === 'stocks_etfs') return 'Stocks / ETFs'
  return titleCase(value)
}

function confidenceLabel(value: DashboardContract['confidence_state']) {
  if (value === 'review_required') return 'Review required'
  return titleCase(value)
}

function confidenceTone(value: DashboardContract['confidence_state']): Tone {
  if (value === 'trusted') return 'up'
  if (value === 'warning' || value === 'provisional' || value === 'review_required') return 'warning'
  if (value === 'blocked') return 'down'
  return 'neutral'
}

function metricScopeBlocked(dashboard: DashboardContract, scope: string) {
  return dashboard.blocked_metric_scopes.includes(scope)
}

function bridgeBarWidth(value: MoneyInput, maxValue: number) {
  const amount = numberValue(value)
  if (amount == null || maxValue <= 0) return '0%'
  return `${Math.max(4, Math.min(100, (Math.abs(amount) / maxValue) * 100))}%`
}

function MetricCard({
  label,
  value,
  detail,
  tone = 'neutral',
}: {
  label: string
  value: string
  detail?: string
  tone?: Tone
}) {
  return (
    <div className="panel panel-bento" style={{ padding: 20 }}>
      <span className="panel-header">{label}</span>
      <div
        style={{
          marginTop: 12,
          fontSize: 30,
          fontWeight: 300,
          letterSpacing: '-0.02em',
          lineHeight: 1.05,
          color: toneColor(tone),
          overflowWrap: 'anywhere',
        }}
      >
        {value}
      </div>
      {detail ? (
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--fg-3)' }}>
          {detail}
        </div>
      ) : null}
    </div>
  )
}

function MiniMetric({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string
  tone?: Tone
}) {
  return (
    <div>
      <div className="panel-header" style={{ marginBottom: 4 }}>{label}</div>
      <div
        style={{
          fontFamily: 'var(--font-geist-mono)',
          fontSize: 13,
          color: toneColor(tone),
          letterSpacing: '-0.01em',
        }}
      >
        {value}
      </div>
    </div>
  )
}

function ReasonList({ reasonCodes }: { reasonCodes: string[] }) {
  if (reasonCodes.length === 0) return null

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {reasonCodes.map(reason => (
        <span key={reason} className="badge-amber">
          {readableToken(reason)}
        </span>
      ))}
    </div>
  )
}

function ValueBridgePanel({ dashboard }: { dashboard: DashboardContract }) {
  const period = dashboard.rolling_30d
  const visibleGain = period.visible && period.investment_gain_usd != null
  const endingValue = period.ending_value_usd ?? dashboard.current_total_value_usd
  const contribution = numberValue(period.external_contributions_usd) ?? 0
  const withdrawal = numberValue(period.external_withdrawals_usd) ?? 0
  const investmentGain = visibleGain ? numberValue(period.investment_gain_usd) : null
  const maxValue = Math.max(
    Math.abs(numberValue(period.starting_value_usd) ?? 0),
    Math.abs(contribution),
    Math.abs(withdrawal),
    Math.abs(investmentGain ?? 0),
    Math.abs(numberValue(endingValue) ?? 0),
    1,
  )

  const steps = [
    {
      label: 'Starting value',
      value: formatUsd(period.starting_value_usd),
      tone: 'neutral' as Tone,
      widthSource: period.starting_value_usd,
    },
    {
      label: 'External contributions',
      value: formatUsd(contribution, { signed: true }),
      tone: contribution === 0 ? 'neutral' as Tone : 'up' as Tone,
      widthSource: contribution,
    },
    {
      label: 'External withdrawals',
      value: formatUsd(-withdrawal, { signed: true }),
      tone: withdrawal === 0 ? 'neutral' as Tone : 'down' as Tone,
      widthSource: withdrawal,
    },
    {
      label: 'Investment gain',
      value: visibleGain ? formatUsd(investmentGain, { signed: true }) : 'Review required',
      tone: visibleGain ? toneForAmount(investmentGain) : 'warning' as Tone,
      widthSource: visibleGain ? investmentGain : null,
    },
    {
      label: 'Ending value',
      value: formatUsd(endingValue),
      tone: 'neutral' as Tone,
      widthSource: endingValue,
    },
  ]

  return (
    <section
      className="panel panel-bento"
      data-mobile-section="overview-value-bridge"
      data-testid="dashboard-value-bridge"
      style={{ padding: 22 }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <span className="panel-header">30D value bridge</span>
        <span className={period.confidence_state === 'trusted' ? 'badge-green' : 'badge-amber'}>
          {confidenceLabel(period.confidence_state)}
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-5" style={{ marginTop: 18 }}>
        {steps.map(step => (
          <div key={step.label} style={{ minWidth: 0 }}>
            <div style={{ height: 66, display: 'flex', alignItems: 'flex-end', background: 'var(--bg-2)', border: '1px solid var(--line-1)', padding: 8 }}>
              <div
                aria-hidden="true"
                style={{
                  width: '100%',
                  height: bridgeBarWidth(step.widthSource, maxValue),
                  minHeight: step.widthSource == null ? 0 : 4,
                  background: toneColor(step.tone),
                  opacity: step.widthSource == null ? 0 : 0.72,
                }}
              />
            </div>
            <div style={{ marginTop: 8, fontSize: 11, color: 'var(--fg-3)' }}>{step.label}</div>
            <div style={{ marginTop: 3, fontFamily: 'var(--font-geist-mono)', fontSize: 12.5, color: toneColor(step.tone), overflowWrap: 'anywhere' }}>
              {step.value}
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 14 }}>
        <ReasonList reasonCodes={period.reason_codes} />
      </div>
    </section>
  )
}

function CurrentValuePanel({ dashboard }: { dashboard: DashboardContract }) {
  const value = dashboard.current_total_value_usd
  const netCapitalBlocked = metricScopeBlocked(dashboard, 'net_capital')

  return (
    <section
      className="panel panel-bento"
      data-mobile-section="overview-summary"
      style={{ padding: 22, minHeight: 238 }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline' }}>
        <span className="panel-header">Current total value</span>
        <span
          style={{
            fontFamily: 'var(--font-geist-mono)',
            fontSize: 10,
            color: 'var(--fg-3)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
          }}
        >
          {new Date(dashboard.as_of).toISOString().slice(0, 10)}
        </span>
      </div>

      <div
        style={{
          marginTop: 18,
          fontSize: 46,
          fontWeight: 300,
          letterSpacing: '-0.035em',
          lineHeight: 0.95,
          color: value == null ? 'var(--warn)' : 'var(--fg-0)',
          overflowWrap: 'anywhere',
        }}
      >
        {value == null ? 'Current value blocked' : formatUsd(value)}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
          gap: 18,
          marginTop: 24,
          paddingTop: 16,
          borderTop: '1px solid var(--line-1)',
        }}
      >
        <MiniMetric
          label={netCapitalBlocked ? 'Net capital unavailable' : 'Net capital at work'}
          value={netCapitalBlocked ? 'Review required' : formatUsd(dashboard.lifetime.net_capital_at_work_usd)}
          tone={netCapitalBlocked ? 'warning' : 'neutral'}
        />
        <MiniMetric
          label={dashboard.lifetime.visible ? 'Lifetime P/L' : 'Lifetime P/L unavailable'}
          value={dashboard.lifetime.visible ? formatUsd(dashboard.lifetime.lifetime_pnl_usd, { signed: true }) : 'Review required'}
          tone={dashboard.lifetime.visible ? toneForAmount(dashboard.lifetime.lifetime_pnl_usd) : 'warning'}
        />
      </div>
    </section>
  )
}

function RollingPeriodPanel({ dashboard }: { dashboard: DashboardContract }) {
  const period = dashboard.rolling_30d
  const visibleGain = period.visible && period.investment_gain_usd != null
  const gainTone = visibleGain ? toneForAmount(period.investment_gain_usd) : 'warning'

  return (
    <section
      className="panel panel-bento"
      data-mobile-section="overview-period"
      style={{ padding: 22, minHeight: 238 }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span className="panel-header">Rolling {period.label}</span>
        <span className={period.confidence_state === 'trusted' ? 'badge-green' : 'badge-amber'}>
          {confidenceLabel(period.confidence_state)}
        </span>
      </div>

      <div style={{ marginTop: 18 }}>
        <div className="panel-header">
          {visibleGain ? '30D investment gain' : '30D investment gain unavailable'}
        </div>
        <div
          style={{
            marginTop: 8,
            fontSize: 34,
            fontWeight: 300,
            letterSpacing: '-0.025em',
            color: toneColor(gainTone),
            overflowWrap: 'anywhere',
          }}
        >
          {visibleGain ? formatUsd(period.investment_gain_usd, { signed: true }) : 'Review required'}
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
          gap: 18,
          marginTop: 22,
          paddingTop: 16,
          borderTop: '1px solid var(--line-1)',
        }}
      >
        <MiniMetric label="External contributions" value={formatUsd(period.external_contributions_usd)} />
        <MiniMetric label="External withdrawals" value={formatUsd(period.external_withdrawals_usd)} />
      </div>

      <div style={{ marginTop: 14 }}>
        <ReasonList reasonCodes={period.reason_codes} />
      </div>
    </section>
  )
}

function ConfidencePanel({
  dashboard,
  syncStatuses,
  onSync,
  syncing,
}: {
  dashboard: DashboardContract
  syncStatuses: SyncStatus[]
  onSync: () => void
  syncing: boolean
}) {
  const tone = confidenceTone(dashboard.confidence_state)
  const action = dashboard.top_reconciliation_action

  return (
    <section
      className="panel panel-bento"
      data-mobile-section="overview-confidence"
      style={{ padding: 22, minHeight: 238 }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline' }}>
        <span className="panel-header">Confidence</span>
        <span className={dashboard.confidence_state === 'trusted' ? 'badge-green' : 'badge-amber'}>
          {confidenceLabel(dashboard.confidence_state)}
        </span>
      </div>

      <div
        style={{
          marginTop: 14,
          fontSize: 24,
          fontWeight: 300,
          color: toneColor(tone),
          letterSpacing: '-0.015em',
        }}
      >
        {action ? `Resolve ${readableToken(action.task_type)}` : 'No accounting action needed.'}
      </div>

      {action ? (
        <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontFamily: 'var(--font-geist-mono)', color: 'var(--fg-0)' }}>{action.asset_symbol}</span>
            <span className="badge-dim">{action.source}</span>
            <span className="badge-amber">{action.severity}</span>
          </div>
          {action.amount_usd != null ? (
            <MiniMetric label="Unresolved value" value={formatUsd(action.amount_usd)} tone="warning" />
          ) : null}
          {action.affected_metric_scopes.length > 0 ? (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {action.affected_metric_scopes.slice(0, 3).map(scope => (
                <span key={scope} className="badge-amber">{readableToken(scope)}</span>
              ))}
            </div>
          ) : null}
          <Link href="/review" className="btn-ghost" style={{ alignSelf: 'flex-start' }}>
            Open accounting review
          </Link>
        </div>
      ) : (
        <div style={{ marginTop: 12 }}>
          <ReasonList reasonCodes={dashboard.reason_codes} />
        </div>
      )}

      <div
        style={{
          marginTop: 18,
          paddingTop: 14,
          borderTop: '1px solid var(--line-1)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontSize: 12, color: 'var(--fg-3)' }}>
          {syncStatuses.length > 0 ? `${syncStatuses.length} sync channel${syncStatuses.length === 1 ? '' : 's'}` : 'Sync status unavailable'}
        </span>
        <button
          type="button"
          onClick={onSync}
          disabled={syncing}
          className="btn-ghost"
          style={{ fontSize: 10, letterSpacing: '0.12em' }}
        >
          {syncing ? 'Syncing...' : 'Sync Binance'}
        </button>
      </div>
    </section>
  )
}

function LifetimeContextPanel({ dashboard }: { dashboard: DashboardContract }) {
  const lifetime = dashboard.lifetime
  const showSensitive = lifetime.visible && lifetime.lifetime_pnl_usd != null
  const netCapitalBlocked = metricScopeBlocked(dashboard, 'net_capital')

  return (
    <section
      className="panel panel-bento"
      data-mobile-section="overview-lifetime"
      style={{ padding: 20 }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span className="panel-header">Capital context</span>
        <span className={lifetime.confidence_state === 'trusted' ? 'badge-green' : 'badge-amber'}>
          {confidenceLabel(lifetime.confidence_state)}
        </span>
      </div>
      <div className="grid gap-4 md:grid-cols-2" style={{ marginTop: 18 }}>
        <MiniMetric label="Gross contributions" value={formatUsd(lifetime.gross_contributions_usd)} />
        <MiniMetric label="Gross withdrawals" value={formatUsd(lifetime.gross_withdrawals_usd)} />
        <MiniMetric
          label={netCapitalBlocked ? 'Net capital unavailable' : 'Net capital at work'}
          value={netCapitalBlocked ? 'Review required' : formatUsd(lifetime.net_capital_at_work_usd)}
          tone={netCapitalBlocked ? 'warning' : 'neutral'}
        />
        <MiniMetric
          label={showSensitive ? 'Lifetime return' : 'Lifetime return unavailable'}
          value={showSensitive ? formatPct(lifetime.return_pct, { signed: true, decimals: 1 }) : 'Review required'}
          tone={showSensitive ? toneForAmount(lifetime.return_pct) : 'warning'}
        />
      </div>
      <div style={{ marginTop: 14 }}>
        <ReasonList reasonCodes={lifetime.reason_codes} />
      </div>
    </section>
  )
}

function DistributionPanel({ dashboard }: { dashboard: DashboardContract }) {
  const buckets = dashboard.asset_type_distribution

  return (
    <section
      className="panel panel-bento"
      data-mobile-section="overview-distribution"
      style={{ padding: 20 }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
        <span className="panel-header">Asset-type distribution</span>
        <span className="badge-dim">{buckets.length} types</span>
      </div>

      {buckets.length === 0 ? (
        <p style={{ marginTop: 18, fontSize: 13, color: 'var(--fg-3)' }}>Distribution unavailable.</p>
      ) : (
        <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {buckets.map(bucket => {
            const percentageVisible = bucket.percentage_state === 'visible' && bucket.percentage != null
            const pct = percentageVisible ? numberValue(bucket.percentage) ?? 0 : 0

            return (
              <div key={bucket.asset_type}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 12, alignItems: 'baseline' }}>
                  <span style={{ fontSize: 13, color: 'var(--fg-0)', fontWeight: 500 }}>
                    {assetTypeLabel(bucket.asset_type)}
                  </span>
                  <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 13, color: 'var(--fg-0)' }}>
                    {formatUsd(bucket.value_usd)}
                  </span>
                  <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 12, color: percentageVisible ? 'var(--fg-2)' : 'var(--warn)' }}>
                    {percentageVisible ? formatPct(bucket.percentage, { decimals: 1 }) : 'Hidden'}
                  </span>
                </div>
	                <div style={{ marginTop: 6, height: 4, background: 'var(--line-1)', overflow: 'hidden' }}>
	                  <div
	                    data-testid={`distribution-bar-${bucket.asset_type}`}
	                    style={{
	                      height: '100%',
	                      width: percentageVisible ? `${Math.max(2, Math.min(100, pct))}%` : '0%',
	                      background: bucket.confidence_state === 'trusted' ? 'var(--fg-1)' : 'var(--warn)',
	                      opacity: percentageVisible ? 0.72 : 0,
	                    }}
	                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function CashReservePanel({ dashboard }: { dashboard: DashboardContract }) {
  const cash = dashboard.cash_reserve

  return (
    <section
      className="panel panel-bento"
      data-mobile-section="overview-cash"
      style={{ padding: 20 }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span className="panel-header">Cash reserve</span>
        <span className={cash.confidence_state === 'trusted' ? 'badge-green' : 'badge-amber'}>
          {confidenceLabel(cash.confidence_state)}
        </span>
      </div>
      <div
        style={{
          marginTop: 14,
          fontSize: 30,
          fontWeight: 300,
          color: 'var(--fg-0)',
          letterSpacing: '-0.02em',
          overflowWrap: 'anywhere',
        }}
      >
        {formatUsd(cash.total_usd)}
      </div>
      <div style={{ marginTop: 18, display: 'grid', gap: 12 }}>
        <MiniMetric label="Stablecoin reserve" value={formatUsd(cash.stablecoin_usd)} />
        <MiniMetric label="Broker cash" value={formatUsd(cash.broker_cash_usd)} />
        <MiniMetric label="Other tracked cash" value={formatUsd(cash.other_tracked_cash_usd)} />
      </div>
      <div style={{ marginTop: 14 }}>
        <ReasonList reasonCodes={cash.reason_codes} />
      </div>
    </section>
  )
}

function HoldingDriversPanel({ dashboard }: { dashboard: DashboardContract }) {
  const drivers = dashboard.holding_drivers

  return (
    <section
      className="panel panel-bento"
      data-mobile-section="overview-drivers"
      style={{ padding: 20 }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
        <span className="panel-header">Holding drivers</span>
        <span className="badge-dim">30D</span>
      </div>

	      {drivers.length === 0 ? (
	        <p style={{ marginTop: 18, fontSize: 13, color: 'var(--fg-3)' }}>No holding drivers yet.</p>
	      ) : (
	        <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
	          {drivers.map(driver => {
	            const valueVisible = driver.value_state === 'visible' && driver.movement_usd != null
	            const flagged = driver.value_state === 'flagged'
	            const tone = valueVisible ? toneForAmount(driver.movement_usd) : 'warning'

            return (
              <div
                key={driver.symbol}
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(64px, 0.7fr) minmax(90px, 1fr)',
                  gap: 12,
                  alignItems: 'baseline',
                  paddingBottom: 12,
                  borderBottom: '1px solid var(--line-1)',
                }}
              >
                <div>
                  <div style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 13, color: 'var(--fg-0)' }}>
                    {driver.symbol}
                  </div>
                  <div style={{ marginTop: 4, fontSize: 11, color: 'var(--fg-3)' }}>
                    {titleCase(driver.direction)}
                  </div>
                </div>
	                <div style={{ textAlign: 'right' }}>
	                  <div style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 15, color: toneColor(tone) }}>
	                    {valueVisible ? formatUsd(driver.movement_usd, { signed: true }) : flagged ? 'Flagged for review' : 'Value hidden'}
	                  </div>
	                  {driver.share_of_known_movement_pct != null && valueVisible ? (
                    <div style={{ marginTop: 4, fontSize: 11, color: 'var(--fg-3)' }}>
                      {formatPct(driver.share_of_known_movement_pct, { decimals: 1 })} of known move
                    </div>
                  ) : null}
                  {driver.reason_codes.length > 0 ? (
                    <div style={{ marginTop: 6, display: 'flex', justifyContent: 'flex-end' }}>
                      <ReasonList reasonCodes={driver.reason_codes.slice(0, 1)} />
                    </div>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function DrilldownPanel({ syncStatuses }: { syncStatuses: SyncStatus[] }) {
  return (
    <details
      className="panel panel-bento"
      data-mobile-section="overview-drilldowns"
      style={{ padding: 18 }}
    >
      <summary
        style={{
          cursor: 'pointer',
          fontFamily: 'var(--font-geist-mono)',
          fontSize: 11,
          color: 'var(--fg-2)',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}
      >
        Raw activity and import logs
      </summary>
      <div className="grid gap-4 md:grid-cols-2" style={{ marginTop: 16 }}>
        <div>
          <div className="panel-header" style={{ marginBottom: 8 }}>Activity drilldowns</div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Link href="/transactions" className="btn-ghost">Transactions</Link>
            <Link href="/import" className="btn-ghost">Imports</Link>
            <Link href="/review" className="btn-ghost">Accounting review</Link>
          </div>
        </div>
        <div>
          <div className="panel-header" style={{ marginBottom: 8 }}>Data freshness</div>
          {syncStatuses.length === 0 ? (
            <p style={{ fontSize: 12, color: 'var(--fg-3)' }}>No sync status available.</p>
          ) : (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {syncStatuses.map(status => (
                <span key={status.name} className={status.degraded ? 'badge-amber' : 'badge-green'}>
                  {status.name}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </details>
  )
}

function DashboardFirstScreen({
  dashboard,
  syncStatuses,
  onSync,
  syncing,
}: {
  dashboard: DashboardContract
  syncStatuses: SyncStatus[]
  onSync: () => void
  syncing: boolean
}) {
  return (
    <>
      <ValueBridgePanel dashboard={dashboard} />

      <section className="grid gap-4 xl:grid-cols-[1.2fr_1fr_1fr]">
        <CurrentValuePanel dashboard={dashboard} />
        <RollingPeriodPanel dashboard={dashboard} />
        <ConfidencePanel
          dashboard={dashboard}
          syncStatuses={syncStatuses}
          onSync={onSync}
          syncing={syncing}
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.9fr_1fr]" data-overview-workflow>
        <DistributionPanel dashboard={dashboard} />
        <CashReservePanel dashboard={dashboard} />
        <HoldingDriversPanel dashboard={dashboard} />
      </section>

      <LifetimeContextPanel dashboard={dashboard} />
      <DrilldownPanel syncStatuses={syncStatuses} />
    </>
  )
}

export default function DashboardPage() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [dashboard, setDashboard] = useState<DashboardContract | null>(null)
  const [syncStatuses, setSyncStatuses] = useState<SyncStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')

    const [dashboardResult, syncResult] = await Promise.allSettled([
      portfolioAPI.dashboard(),
      syncAPI.status(),
    ])

    if (dashboardResult.status === 'rejected') {
      const reason = dashboardResult.reason
      setDashboard(null)
      setSyncStatuses(syncResult.status === 'fulfilled' ? syncResult.value : [])
      setError(reason instanceof Error ? reason.message : 'Failed to load dashboard data')
      setLoading(false)
      return
    }

    setDashboard(dashboardResult.value)
    setSyncStatuses(syncResult.status === 'fulfilled' ? syncResult.value : [])
    setLoading(false)
  }, [])

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) {
      router.push('/login')
      return
    }
    void load()
  }, [isAuthenticated, isLoading, load, router])

  async function handleSync() {
    setSyncing(true)
    setSyncMsg('')
    try {
      const result = await syncAPI.binance()
      if (result.error) {
        setSyncMsg(`Error: ${result.error}`)
      } else {
        setSyncMsg(`Synced ${result.synced} records`)
        await load()
      }
    } catch (err: unknown) {
      setSyncMsg(err instanceof Error ? err.message : 'Sync failed')
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
          <div style={{ marginTop: 16, fontSize: 13, color: 'var(--fg-0)', fontWeight: 500 }}>
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

      <main style={{ paddingTop: 60, paddingBottom: 40 }} className="md:ml-[220px]">
        <div
          style={{ padding: '22px clamp(16px, 2vw, 32px) 0', maxWidth: 1600, margin: '0 auto' }}
          className="space-y-5"
        >
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
          ) : dashboard ? (
            <DashboardFirstScreen
              dashboard={dashboard}
              syncStatuses={syncStatuses}
              onSync={handleSync}
              syncing={syncing}
            />
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
        <span className="panel-header">Loading dashboard</span>
        <div style={{ marginTop: 10, fontSize: 13, color: 'var(--fg-2)' }}>
          Preparing trusted portfolio view<span className="cursor" />
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr_1fr]">
        {[0, 1, 2].map(index => (
          <div key={index} className="panel" style={{ height: 220 }}>
            <div style={{ padding: 20 }}>
              <div style={{ height: 10, width: '50%', background: 'var(--line-2)', marginBottom: 14 }} className="animate-pulse" />
              <div style={{ height: 36, width: '70%', background: 'var(--line-1)' }} className="animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
