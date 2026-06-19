import { type PerformanceSummary as PerformanceSummaryData, type PerformanceScope } from '@/lib/api'

function fmtCurrency(value: number | null | undefined, decimals = 0) {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

function fmtPercent(value: number | null | undefined) {
  if (value == null) return '—'
  const scaledValue = value * 100
  const sign = scaledValue >= 0 ? '+' : ''
  return `${sign}${scaledValue.toFixed(2)}%`
}

function metricTone(value: number | null | undefined) {
  if (value == null || value === 0) return 'val-muted'
  return value > 0 ? 'val-pos' : 'val-neg'
}

function scopeLabel(scopeName: string) {
  if (scopeName === 'combined') return 'Combined'
  return scopeName.replace(/_/g, ' ')
}

function ScopeRow({ label, scope }: { label: string; scope: PerformanceScope }) {
  return (
    <div className="surface-row px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="metric-label">{label}</p>
          <p className="mt-2 text-lg font-semibold tracking-[-0.03em] text-bright">
            {fmtCurrency(scope.current_value_usd, 2)}
          </p>
        </div>
        <div className="text-right">
          <p className={`font-mono text-sm ${metricTone(scope.total_pnl_usd)}`}>
            {fmtCurrency(scope.total_pnl_usd, 2)}
          </p>
          <p className="mt-1 text-xs text-dim">total P&amp;L</p>
        </div>
      </div>
      <div className="mt-3 grid gap-3 text-xs text-dim sm:grid-cols-3">
        <div>
          <span className="metric-label">Net invested</span>
          <p className="mt-1 font-mono text-sm text-bright">{fmtCurrency(scope.net_invested_capital_usd, 2)}</p>
        </div>
        <div>
          <span className="metric-label">Realized</span>
          <p className={`mt-1 font-mono text-sm ${metricTone(scope.realized_pnl_usd)}`}>{fmtCurrency(scope.realized_pnl_usd, 2)}</p>
        </div>
        <div>
          <span className="metric-label">Unrealized</span>
          <p className={`mt-1 font-mono text-sm ${metricTone(scope.unrealized_pnl_usd)}`}>{fmtCurrency(scope.unrealized_pnl_usd, 2)}</p>
        </div>
      </div>
    </div>
  )
}

interface PerformanceSummaryPanelProps {
  summary: PerformanceSummaryData | null
}

export function PerformanceSummaryPanel({ summary }: PerformanceSummaryPanelProps) {
  if (!summary) {
    return (
      <div className="panel panel-bento p-5">
        <p className="panel-header">Performance ledger</p>
        <h3 className="panel-title mt-2">Performance summary</h3>
        <p className="mt-6 text-sm text-dim">Performance summary is unavailable right now.</p>
      </div>
    )
  }

  const institutionEntries = Object.entries(summary.institutions)
  const comparison = summary.comparisons.binance_vs_xtb
  const combined = summary.combined

  return (
    <div className="panel panel-bento p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="panel-header">Performance ledger</p>
          <h3 className="panel-title mt-2">Performance summary</h3>
        </div>
        <span className="badge-blue">{institutionEntries.length + 1} scopes</span>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[0.85fr_1.15fr]">
        <div className="space-y-3">
          <div className="surface-row p-4">
            <p className="metric-label">Combined P&amp;L</p>
            <p className={`mt-2 text-3xl font-semibold tracking-[-0.04em] ${metricTone(combined.total_pnl_usd)}`}>
              {fmtCurrency(combined.total_pnl_usd, 2)}
            </p>
            <p className="mt-2 text-sm text-dim">
              {`Current value ${fmtCurrency(combined.current_value_usd, 2)} · XIRR ${fmtPercent(combined.xirr)}`}
            </p>
          </div>
          <div className="surface-row p-4">
            <p className="metric-label">Capital flows</p>
            <div className="mt-3 space-y-2 text-sm text-dim">
              <div className="flex items-center justify-between gap-3">
                <span>Deposits</span>
                <span className="font-mono text-bright">{fmtCurrency(combined.gross_deposits_usd, 2)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Withdrawals</span>
                <span className="font-mono text-bright">{fmtCurrency(combined.gross_withdrawals_usd, 2)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Rewards</span>
                <span className="font-mono text-bright">{fmtCurrency(combined.reward_income_usd, 2)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Fees</span>
                <span className="font-mono text-bright">{fmtCurrency(combined.fees_usd, 2)}</span>
              </div>
            </div>
          </div>
          <div className="surface-row p-4">
            <p className="metric-label">Binance vs XTB delta</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <p className={`font-mono text-sm ${metricTone(comparison?.total_pnl_delta_usd)}`}>
                  {fmtCurrency(comparison?.total_pnl_delta_usd, 2)}
                </p>
                <p className="mt-1 text-xs text-dim">P&amp;L delta</p>
              </div>
              <div>
                <p className={`font-mono text-sm ${metricTone(comparison?.net_invested_delta_usd)}`}>
                  {fmtCurrency(comparison?.net_invested_delta_usd, 2)}
                </p>
                <p className="mt-1 text-xs text-dim">Net invested delta</p>
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <ScopeRow label={scopeLabel('combined')} scope={combined} />
          {institutionEntries.map(([name, scope]) => (
            <ScopeRow key={name} label={scopeLabel(name)} scope={scope} />
          ))}
        </div>
      </div>
    </div>
  )
}
