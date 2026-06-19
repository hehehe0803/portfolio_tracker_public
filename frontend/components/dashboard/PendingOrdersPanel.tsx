import { type PendingOrder } from '@/lib/api'

function fmtPrice(value: number | null | undefined) {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function orderBadge(orderType: string) {
  switch (orderType) {
    case 'limit':
      return 'badge-blue'
    case 'stop':
      return 'badge-amber'
    default:
      return 'badge-dim'
  }
}

interface PendingOrdersPanelProps {
  orders: PendingOrder[]
  unavailable?: boolean
}

export function PendingOrdersPanel({ orders, unavailable = false }: PendingOrdersPanelProps) {
  return (
    <div className="panel panel-bento p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="panel-header">Execution queue</p>
          <h3 className="panel-title mt-2">Pending orders</h3>
        </div>
        <span className="badge-dim">{unavailable ? 'Unavailable' : `${orders.length} open`}</span>
      </div>

      {unavailable ? (
        <p className="mt-6 text-sm text-dim">Pending orders are temporarily unavailable.</p>
      ) : orders.length === 0 ? (
        <p className="mt-6 text-sm text-dim">No open or pending orders are currently tracked.</p>
      ) : (
        <div className="mt-6 space-y-3">
          {orders.map(order => (
            <div key={`${order.institution}-${order.external_order_id}`} className="surface-row px-4 py-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-bright">{order.symbol}</span>
                    <span className={orderBadge(order.order_type)}>{order.order_type}</span>
                    <span className="badge-dim">{order.institution}</span>
                    <span className={order.side === 'buy' ? 'badge-green' : 'badge-red'}>{order.side}</span>
                  </div>
                  <div className="mt-2 text-xs text-dim">
                    {`${order.status} · ${order.placed_at ? new Date(order.placed_at).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : 'Placement time unavailable'}`}
                  </div>
                </div>
                <div className="grid gap-3 text-left text-sm md:grid-cols-3 md:text-right">
                  <div>
                    <p className="metric-label">Quantity</p>
                    <p className="mt-1 font-mono text-bright">{order.quantity.toLocaleString('en-US', { maximumFractionDigits: 8 })}</p>
                  </div>
                  <div>
                    <p className="metric-label">Limit</p>
                    <p className="mt-1 font-mono text-bright">{fmtPrice(order.limit_price)}</p>
                  </div>
                  <div>
                    <p className="metric-label">Stop</p>
                    <p className="mt-1 font-mono text-bright">{fmtPrice(order.stop_price)}</p>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
