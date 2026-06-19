import { type Transaction } from '@/lib/api'

function txAccentColor(type: string): string {
  if (type.includes('buy') || type.includes('deposit') || type.includes('snapshot')) {
    return 'var(--primary)'
  }
  if (type.includes('sell') || type.includes('withdrawal')) {
    return 'var(--red)'
  }
  return 'var(--amber)'
}

function txLabelClass(type: string): string {
  if (type.includes('buy') || type.includes('deposit') || type.includes('snapshot')) return 'val-pos'
  if (type.includes('sell') || type.includes('withdrawal')) return 'val-neg'
  return 'text-amber'
}

interface ActivityFeedProps {
  transactions: Transaction[]
}

export function ActivityFeed({ transactions }: ActivityFeedProps) {
  const recent = transactions.slice(0, 8)

  return (
    <div className="panel panel-bento p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="panel-header">Flow log</p>
          <h3 className="panel-title mt-2">Recent activity</h3>
        </div>
        <span className="badge-dim">{recent.length} events</span>
      </div>

      {recent.length === 0 ? (
        <p className="mt-6 text-sm text-dim">No transactions yet.</p>
      ) : (
        <div className="mt-6 space-y-3">
          {recent.map(tx => (
            <div
              key={tx.id}
              className="surface-row flex flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:justify-between"
              style={{ boxShadow: `inset 3px 0 0 ${txAccentColor(tx.type)}` }}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`uppercase-label ${txLabelClass(tx.type)}`}>
                    {tx.type.replace(/_/g, ' ')}
                  </span>
                  <span className="text-sm font-semibold text-bright">{tx.asset}</span>
                  <span className="badge-dim">{tx.institution}</span>
                </div>
                <div className="mt-2 text-xs text-dim">
                  {`${new Date(tx.timestamp).toISOString().slice(0, 10)} · ${tx.asset_type}`}
                </div>
              </div>
              <div className="text-left md:text-right">
                <div className="font-mono text-sm text-bright">
                  {tx.quantity.toLocaleString('en-US', { maximumFractionDigits: 6 })}
                </div>
                <div className="mt-1 text-xs text-dim">
                  {tx.total_usd != null ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(tx.total_usd) : 'No notional'}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
