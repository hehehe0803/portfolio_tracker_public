import { type SyncStatus } from '@/lib/api'

function statusBadge(status: SyncStatus) {
  if (status.degraded) return 'badge-amber'
  if (status.last_sync_at) return 'badge-green'
  return 'badge-dim'
}

function dotClass(status: SyncStatus) {
  if (status.degraded) return 'signal-dot signal-dot-amber'
  if (status.last_sync_at) return 'signal-dot'
  return 'signal-dot signal-dot-cyan'
}

function labelFor(status: SyncStatus) {
  if (status.degraded) return 'Degraded'
  if (status.last_sync_at) return 'Healthy'
  return 'Idle'
}

interface SyncStatusPanelProps {
  statuses: SyncStatus[]
  unavailable?: boolean
}

export function SyncStatusPanel({ statuses, unavailable = false }: SyncStatusPanelProps) {
  return (
    <div className="panel panel-bento p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="panel-header">Sync telemetry</p>
          <h3 className="panel-title mt-2">Institution sync state</h3>
        </div>
        <span className="badge-dim">{unavailable ? 'Unavailable' : `${statuses.length} channels`}</span>
      </div>

      {unavailable ? (
        <p className="mt-6 text-sm text-dim">Institution sync status is temporarily unavailable.</p>
      ) : statuses.length === 0 ? (
        <p className="mt-6 text-sm text-dim">No institution sync channels are configured yet.</p>
      ) : (
        <div className="mt-6 space-y-3">
          {statuses.map(status => (
            <div key={status.name} className="surface-row px-4 py-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold capitalize text-bright">{status.name}</span>
                    <span className={statusBadge(status)}>
                      <span className={dotClass(status)} />
                      {labelFor(status)}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-dim">
                    {`Last sync ${status.last_sync_at ? new Date(status.last_sync_at).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : 'not yet recorded'}`}
                  </p>
                </div>
                <div className="max-w-lg text-sm text-dim md:text-right">
                  {status.warning ? <p className="text-amber">{status.warning}</p> : null}
                  {status.note ? <p className="mt-1">{status.note}</p> : null}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
