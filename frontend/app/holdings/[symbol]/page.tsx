'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { NotePanel } from '@/components/intelligence/NotePanel'
import { useAuth } from '@/components/providers/auth-provider'
import { portfolioAPI, type AssetDetailContract } from '@/lib/api'

type TrustBlocker = AssetDetailContract['trust_blockers'][number]

function asNumber(value: string | number | null | undefined) {
  if (value == null) return null
  const numeric = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function fmtUsd(value: string | number | null | undefined, dec = 2) {
  const numeric = asNumber(value)
  if (numeric == null) return 'Unavailable'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  }).format(numeric)
}

function fmtPct(value: string | number | null | undefined) {
  const numeric = asNumber(value)
  if (numeric == null) return 'Unavailable'
  return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

function fmtQty(value: string | number | null | undefined) {
  const numeric = asNumber(value)
  if (numeric == null) return 'Unavailable'
  if (Math.abs(numeric) > 0 && Math.abs(numeric) < 0.001) return numeric.toExponential(2)
  if (Math.abs(numeric) < 1) return numeric.toFixed(4)
  if (Math.abs(numeric) < 100) return numeric.toFixed(2)
  return numeric.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function tone(value: string | number | null | undefined) {
  const numeric = asNumber(value)
  if (numeric == null || numeric === 0) return 'var(--fg-2)'
  return numeric > 0 ? 'var(--pl-up)' : 'var(--pl-dn)'
}

function humanize(value: string | null | undefined) {
  if (!value) return 'unknown'
  return value.replace(/_/g, ' ')
}

function isBlockingConfidence(value: string | null | undefined) {
  return value === 'blocked' || value === 'review_required'
}

function fmtDateTime(value: string | null | undefined) {
  if (!value) return 'No timestamp'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toISOString().slice(0, 16).replace('T', ' ')
}

function evidenceReason(task: TrustBlocker) {
  const reason = task.evidence.reason
  return typeof reason === 'string' ? reason : null
}

function metricStyle(color = 'var(--fg-0)') {
  return {
    marginTop: 8,
    fontFamily: 'var(--font-geist-mono)',
    fontSize: 19,
    fontWeight: 500,
    color,
  }
}

function MetricCard({
  label,
  value,
  sub,
  color,
  testId,
}: {
  label: string
  value: string
  sub?: string
  color?: string
  testId?: string
}) {
  return (
    <div data-testid={testId} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 12, minWidth: 0 }}>
      <div className="panel-header">{label}</div>
      <div style={metricStyle(color)}>{value}</div>
      {sub ? <div style={{ marginTop: 5, fontSize: 11.5, color: 'var(--fg-3)', lineHeight: 1.5 }}>{sub}</div> : null}
    </div>
  )
}

export default function HoldingDetailPage() {
  const params = useParams<{ symbol: string }>()
  const symbol = decodeURIComponent(params.symbol || '').toUpperCase()
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [detail, setDetail] = useState<AssetDetailContract | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setDetail(await portfolioAPI.assetDetail(symbol))
    } catch (e) {
      setDetail(null)
      setError(e instanceof Error ? e.message : 'Asset detail failed to load')
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) {
      router.push('/login')
      return
    }
    if (!symbol) return
    void load()
  }, [isAuthenticated, isLoading, load, router, symbol])

  if (isLoading || !isAuthenticated) return null

  const current = detail?.current_position
  const currentPositionPnlBlocked =
    current?.current_position_pnl_usd == null && isBlockingConfidence(current?.confidence_state)
  const currentPositionPnlValue =
    current?.current_position_pnl_usd != null
      ? fmtUsd(current.current_position_pnl_usd)
      : currentPositionPnlBlocked
        ? 'Blocked'
        : 'Unavailable'
  const currentPositionPnlSub =
    current?.current_position_pnl_pct != null
      ? fmtPct(current.current_position_pnl_pct)
      : currentPositionPnlBlocked
        ? `Blocked until ${humanize(current?.reason_codes[0]) || 'accounting review'} is resolved.`
        : 'Percent unavailable'
  const lifetimeVisible = detail?.lifetime.visible === true
  const lifetimeBlocked =
    !lifetimeVisible && isBlockingConfidence(detail?.lifetime.confidence_state)
  const lifetimeReason = humanize(detail?.lifetime.reason_codes[0])
  const lifetimeValue = lifetimeVisible ? undefined : lifetimeBlocked ? 'Blocked' : 'Unavailable'
  const lifetimeSub = lifetimeVisible
    ? `${fmtUsd(detail?.lifetime.contribution_basis_usd)} contribution basis`
    : lifetimeBlocked
      ? `Blocked until accounting review resolves ${lifetimeReason}.`
      : `Unavailable while ${lifetimeReason} remains ${humanize(detail?.lifetime.confidence_state)}.`

  return (
    <div className="min-h-screen">
      <Header />
      <Sidebar />
      <main className="px-4 pb-8 pt-[60px] md:ml-[220px] md:px-6 lg:px-8">
        <div className="mx-auto max-w-[1280px] space-y-4 py-4">
          <section data-mobile-section="holding-summary" className="panel panel-bento" style={{ padding: 24 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
              <div style={{ minWidth: 240 }}>
                <div className="panel-header">Asset detail</div>
                <h1 style={{ marginTop: 10, fontSize: 32, lineHeight: 1, fontWeight: 400, color: 'var(--fg-0)' }}>
                  {detail?.symbol ?? (symbol || 'Holding')}
                </h1>
                <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  <span className="badge-dim">{detail?.asset_type ?? 'Unknown type'}</span>
                  <span className="badge-dim">as of {fmtDateTime(detail?.as_of)}</span>
                  <span className="badge-dim">{humanize(current?.confidence_state)} position confidence</span>
                </div>
              </div>
              <div style={{ textAlign: 'right', minWidth: 220 }}>
                <div className="panel-header">Current position value</div>
                <div style={{ marginTop: 10, fontSize: 28, fontWeight: 300, color: 'var(--fg-0)' }}>
                  {loading ? 'Loading...' : fmtUsd(current?.current_value_usd)}
                </div>
                <div style={{ marginTop: 6, fontFamily: 'var(--font-geist-mono)', fontSize: 11, color: 'var(--fg-3)' }}>
                  Quantity {fmtQty(current?.quantity)}
                </div>
              </div>
            </div>
            <div style={{ marginTop: 18 }}>
              <Link href="/portfolio" style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)', textDecoration: 'none' }}>
                Back to portfolio details
              </Link>
            </div>
            {error ? (
              <div style={{ marginTop: 16, border: '1px solid rgba(201,119,102,0.28)', color: 'var(--pl-dn)', padding: '12px 14px' }}>
                {error}
              </div>
            ) : null}
          </section>

          {!loading && !detail && !error ? (
            <section className="panel" style={{ padding: 20, color: 'var(--fg-3)' }}>
              This symbol is not currently present in the asset detail contract.
            </section>
          ) : null}

          {!detail ? null : (
          <>
          <section data-mobile-section="holding-health" className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
            <div className="panel" style={{ padding: 20 }}>
              <div className="panel-header">Current position</div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" style={{ marginTop: 14 }}>
                <MetricCard label="Quantity" value={loading ? 'Loading...' : fmtQty(current?.quantity)} />
                <MetricCard label="Average cost" value={fmtUsd(current?.average_cost_usd)} />
                <MetricCard label="Current price" value={fmtUsd(current?.current_price_usd)} />
                <MetricCard
                  label="Current-position P&L"
                  value={currentPositionPnlValue}
                  sub={currentPositionPnlSub}
                  color={currentPositionPnlBlocked ? 'var(--fg-2)' : tone(current?.current_position_pnl_usd)}
                  testId="current-position-pnl"
                />
              </div>
            </div>

            <div className="panel" style={{ padding: 20 }}>
              <div className="panel-header">Capital allocated</div>
              <div style={{ ...metricStyle('var(--fg-0)'), fontSize: 24 }}>{fmtUsd(detail?.capital_allocated_usd)}</div>
              <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--fg-3)', lineHeight: 1.6 }}>
                Capital allocated is shown separately from current-position P&L and lifetime contribution state.
              </div>
            </div>
          </section>

          <section data-mobile-section="holding-holdings" className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <div className="panel" data-testid="lifetime-contribution" style={{ padding: 20 }}>
              <div className="panel-header">Lifetime contribution P&L</div>
              <div style={{ marginTop: 14, display: 'grid', gap: 12 }}>
                <MetricCard
                  label="Contribution basis"
                  value={lifetimeValue ?? fmtUsd(detail.lifetime.contribution_basis_usd)}
                  sub={lifetimeSub}
                  color={!lifetimeVisible ? 'var(--fg-2)' : 'var(--fg-0)'}
                />
                <MetricCard
                  label="Contribution P&L"
                  value={lifetimeValue ?? fmtUsd(detail.lifetime.contribution_pnl_usd)}
                  sub={
                    lifetimeVisible
                      ? humanize(detail.lifetime.confidence_state)
                      : lifetimeBlocked
                        ? 'Sensitive lifetime/contribution values are hidden while confidence is blocked.'
                        : `Sensitive lifetime/contribution values are unavailable while confidence is ${humanize(detail.lifetime.confidence_state)}.`
                  }
                  color={!lifetimeVisible ? 'var(--fg-2)' : tone(detail.lifetime.contribution_pnl_usd)}
                />
              </div>
            </div>

            <div className="panel" style={{ padding: 20 }}>
              <div className="panel-header">Recent movement and driver</div>
              <div style={{ marginTop: 14, display: 'grid', gap: 12 }}>
                <MetricCard
                  label={detail?.recent_movement ? `${detail.recent_movement.period_label} movement` : 'Recent movement'}
                  value={
                    detail?.recent_movement?.value_state === 'hidden'
                      ? 'Hidden'
                      : fmtUsd(detail?.recent_movement?.movement_usd)
                  }
                  sub={`${humanize(detail?.recent_movement?.direction)} · ${humanize(detail?.recent_movement?.confidence_state)}`}
                  color={tone(detail?.recent_movement?.movement_usd)}
                />
                <div style={{ borderTop: '1px solid var(--line-1)', paddingTop: 12 }}>
                  <div className="panel-header">Driver explanation</div>
                  <div style={{ marginTop: 8, fontSize: 12.5, color: 'var(--fg-1)', lineHeight: 1.6 }}>
                    {detail?.driver_explanation?.explanation ?? 'No trusted driver explanation is available yet.'}
                  </div>
                  {detail?.driver_explanation?.share_of_known_movement_pct ? (
                    <div style={{ marginTop: 8, fontFamily: 'var(--font-geist-mono)', fontSize: 11, color: 'var(--fg-3)' }}>
                      {fmtPct(detail.driver_explanation.share_of_known_movement_pct)} of known {detail.driver_explanation.period_label} movement
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <div data-mobile-section="holding-action-surfaces" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <NotePanel entityType="asset" entityId={symbol} title={`${symbol} notes`} />
              <div className="panel" style={{ padding: 20 }}>
                <div className="panel-header">Trust blockers</div>
                <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {(detail?.trust_blockers ?? []).length === 0 ? (
                    <div style={{ color: 'var(--fg-3)', fontSize: 11.5 }}>No material asset-level accounting blockers.</div>
                  ) : (
                    detail?.trust_blockers.map(task => (
                      <div key={task.task_id} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                          <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-0)' }}>
                            {humanize(task.task_type)}
                          </span>
                          <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: task.severity === 'severe' ? 'var(--pl-dn)' : 'var(--fg-3)' }}>
                            {humanize(task.severity)}
                          </span>
                        </div>
                        <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--fg-2)', lineHeight: 1.6 }}>
                          {evidenceReason(task) ?? `${task.source} ${task.asset_symbol} task affects ${task.affected_metric_scopes.map(humanize).join(', ')}.`}
                        </div>
                        <div style={{ marginTop: 6, fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>
                          {fmtDateTime(task.occurred_at)}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>

            <div data-mobile-section="holding-activity" className="panel" style={{ padding: 20 }}>
              <details data-testid="raw-asset-drilldowns">
                <summary style={{ cursor: 'pointer' }}>
                  <span className="panel-header">Raw activity and import logs</span>
                </summary>
                <div style={{ marginTop: 12, borderTop: '1px solid var(--line-1)', paddingTop: 12, fontSize: 11.5, color: 'var(--fg-3)', lineHeight: 1.6 }}>
                  Raw transactions, activity, import rows, and logs are kept out of the primary asset detail view.
                  Use this drilldown when the trusted contract or accounting review task needs source evidence.
                </div>
                {(detail?.trust_blockers ?? []).length > 0 ? (
                  <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
                    {detail?.trust_blockers.map(task => (
                      <div key={`raw-${task.task_id}`} style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10 }}>
                        <div style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-0)' }}>
                          {task.task_id}
                        </div>
                        <div style={{ marginTop: 4, fontSize: 11.5, color: 'var(--fg-3)' }}>
                          {task.source} · {task.asset_symbol} · {task.affected_metric_scopes.map(humanize).join(', ')}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </details>
            </div>
          </section>
          </>
          )}
        </div>
      </main>
    </div>
  )
}
