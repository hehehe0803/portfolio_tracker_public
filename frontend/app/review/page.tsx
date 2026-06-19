'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { useAuth } from '@/components/providers/auth-provider'
import {
  accountingReviewAPI,
  type AccountingReviewAction,
  type AccountingReviewDecisionRequest,
  type AccountingReviewQueue,
  type AccountingReviewTask,
  type InternalTransferDecision,
  type ManualCostBasisDecision,
} from '@/lib/api'

const ACCOUNTING_ACTIONS: AccountingReviewAction[] = [
  'internal_transfer',
  'personal_withdrawal',
  'import_approval',
  'manual_cost_basis',
  'unknown_cost_basis',
  'unknown',
]

const ACTION_LABELS: Record<AccountingReviewAction, string> = {
  internal_transfer: 'Internal transfer',
  personal_withdrawal: 'Personal withdrawal',
  import_approval: 'Import missing data',
  manual_cost_basis: 'Manual cost basis',
  unknown_cost_basis: 'Unknown cost basis',
  unknown: 'Keep unresolved',
}

const ACTION_BADGES: Record<AccountingReviewAction, string> = {
  internal_transfer: 'badge-green',
  personal_withdrawal: 'badge-amber',
  import_approval: 'badge-blue',
  manual_cost_basis: 'badge-blue',
  unknown_cost_basis: 'badge-red',
  unknown: 'badge-dim',
}

interface AccountingDetailInputs {
  to_source?: string
  to_evidence_key?: string
  to_quantity?: string
  fee_quantity?: string
  fee_asset_symbol?: string
  basis_quantity?: string
  cost_basis_usd?: string
  unit_cost_usd?: string
  basis_method?: string
}

function isAccountingAction(value: unknown): value is AccountingReviewAction {
  return typeof value === 'string' && ACCOUNTING_ACTIONS.includes(value as AccountingReviewAction)
}

function candidateAction(candidate: Record<string, unknown>): AccountingReviewAction | null {
  return isAccountingAction(candidate.action) ? candidate.action : null
}

function candidateText(candidate: Record<string, unknown>, key: string): string | undefined {
  const value = candidate[key]
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return undefined
}

function candidateLabel(candidate: Record<string, unknown>, action: AccountingReviewAction) {
  return candidateText(candidate, 'label') ?? ACTION_LABELS[action]
}

function fmtEnum(value: string) {
  return value.replace(/_/g, ' ').toUpperCase()
}

function fmtScope(value: string) {
  return value.replace(/_/g, ' ').toUpperCase()
}

function fmtUsd(value: string | number | null | undefined) {
  if (value == null || value === '') return '-'
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return String(value)
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed)
}

function fmtQuantity(quantity: string | number | null | undefined, symbol: string) {
  if (quantity == null || quantity === '') return '-'
  return `${quantity} ${symbol}`
}

function fmtDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function evidenceValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(evidenceValue).join(', ')
  if (value == null) return 'null'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function detailText(details: AccountingDetailInputs, key: keyof AccountingDetailInputs): string | undefined {
  const value = details[key]?.trim()
  return value || undefined
}

function positiveDecimal(value: string | undefined): boolean {
  if (!value) return false
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0
}

function nonNegativeDecimal(value: string | undefined): boolean {
  if (!value) return true
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0
}

function buildInternalTransfer(
  candidate: Record<string, unknown>,
  details: AccountingDetailInputs
): InternalTransferDecision | null {
  const to_source = detailText(details, 'to_source') ?? candidateText(candidate, 'to_source')
  const to_evidence_key = detailText(details, 'to_evidence_key') ?? candidateText(candidate, 'to_evidence_key')
  const to_quantity = detailText(details, 'to_quantity') ?? candidateText(candidate, 'to_quantity')
  if (!to_source || !to_evidence_key || !to_quantity) return null
  if (!positiveDecimal(to_quantity)) return null
  const fee_quantity = detailText(details, 'fee_quantity') ?? candidateText(candidate, 'fee_quantity')
  const fee_asset_symbol = detailText(details, 'fee_asset_symbol') ?? candidateText(candidate, 'fee_asset_symbol')
  if (!nonNegativeDecimal(fee_quantity)) return null
  return {
    to_source,
    to_evidence_key,
    to_quantity,
    ...(fee_quantity ? { fee_quantity } : {}),
    ...(fee_asset_symbol ? { fee_asset_symbol } : {}),
  }
}

function buildCostBasis(
  candidate: Record<string, unknown>,
  details: AccountingDetailInputs
): ManualCostBasisDecision {
  const quantity = detailText(details, 'basis_quantity') ?? candidateText(candidate, 'quantity')
  const cost_basis_usd = detailText(details, 'cost_basis_usd') ?? candidateText(candidate, 'cost_basis_usd')
  const unit_cost_usd = detailText(details, 'unit_cost_usd') ?? candidateText(candidate, 'unit_cost_usd')
  const basis_method = detailText(details, 'basis_method') ?? candidateText(candidate, 'basis_method')
  return {
    ...(quantity ? { quantity } : {}),
    ...(cost_basis_usd ? { cost_basis_usd } : {}),
    ...(unit_cost_usd ? { unit_cost_usd } : {}),
    ...(basis_method ? { basis_method } : {}),
  }
}

function buildDecisionPayload(
  task: AccountingReviewTask,
  candidate: Record<string, unknown>,
  rationale: string,
  details: AccountingDetailInputs
): AccountingReviewDecisionRequest | { error: string } {
  const action = candidateAction(candidate)
  if (!action) return { error: 'Unsupported accounting action from queue data.' }

  const payload: AccountingReviewDecisionRequest = {
    task_id: task.task_id,
    action,
    idempotency_key: `${task.task_id}-${action}-${Date.now()}`,
    rationale: rationale.trim() || null,
  }

  if (action === 'internal_transfer') {
    const internalTransfer = buildInternalTransfer(candidate, details)
    if (!internalTransfer) {
      return { error: 'Enter destination source, evidence key, and quantity before resolving as an internal transfer.' }
    }
    payload.internal_transfer = internalTransfer
  }

  if (action === 'manual_cost_basis') {
    const costBasis = buildCostBasis(candidate, details)
    if (!costBasis.cost_basis_usd && !(costBasis.quantity && costBasis.unit_cost_usd)) {
      return { error: 'Enter total cost basis or quantity plus unit cost before resolving manual cost basis.' }
    }
    payload.cost_basis = costBasis
  }

  return payload
}

function severityBadge(severity: string) {
  if (severity === 'blocked' || severity === 'severe') return 'badge-red'
  if (severity === 'review_required' || severity === 'material') return 'badge-amber'
  return 'badge-dim'
}

function QueueSummary({ queue }: { queue: AccountingReviewQueue }) {
  const blocked = queue.tasks.filter(task => task.severity === 'blocked' || task.severity === 'severe').length
  const affectedScopes = new Set(queue.tasks.flatMap(task => task.affected_metric_scopes))

  return (
    <section className="grid gap-3 md:grid-cols-3">
      <div className="panel panel-bento p-5">
        <div className="panel-header">Open tasks</div>
        <p className="metric-value mt-2">{queue.tasks.length}</p>
        <p className="metric-sub mt-2">
          {queue.tasks.length === 1 ? '1 open accounting task' : `${queue.tasks.length} open accounting tasks`}
        </p>
      </div>
      <div className="panel panel-bento p-5">
        <div className="panel-header">Blocked tasks</div>
        <p className="metric-value mt-2">{blocked}</p>
        <p className="metric-sub mt-2">Tasks marked blocked or severe</p>
      </div>
      <div className="panel panel-bento p-5">
        <div className="panel-header">Metric scopes</div>
        <p className="metric-value mt-2">{affectedScopes.size}</p>
        <p className="metric-sub mt-2">Affected by unresolved accounting evidence</p>
      </div>
    </section>
  )
}

function TaskEvidence({ task }: { task: AccountingReviewTask }) {
  const entries = Object.entries(task.evidence ?? {}).slice(0, 8)
  if (entries.length === 0) {
    return <p className="mt-2 text-xs text-dim">No structured evidence was attached to this task.</p>
  }

  return (
    <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="surface-row px-3 py-2 font-mono text-dim">
          {key}: {evidenceValue(value)}
        </div>
      ))}
    </div>
  )
}

function CandidateButton({
  candidate,
  disabled,
  onSubmit,
}: {
  candidate: Record<string, unknown>
  disabled: boolean
  onSubmit: () => void
}) {
  const action = candidateAction(candidate)
  if (!action) return null
  const confidence = candidateText(candidate, 'confidence')
  const effect = candidateText(candidate, 'effect')

  return (
    <button
      type="button"
      className="btn-ghost flex h-full flex-col items-start justify-start gap-2 whitespace-normal text-left"
      disabled={disabled}
      onClick={onSubmit}
    >
      <span className={ACTION_BADGES[action]}>{ACTION_LABELS[action]}</span>
      <span className="text-bright text-xs">{candidateLabel(candidate, action)}</span>
      {effect ? <span className="text-dim text-[11px] normal-case">{effect}</span> : null}
      {confidence ? (
        <span className="text-dim text-[11px] normal-case">Candidate confidence: {confidence.replace(/_/g, ' ')}</span>
      ) : null}
    </button>
  )
}

function DetailField({
  id,
  label,
  value,
  onChange,
  placeholder,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <label htmlFor={id} className="block">
      <span className="uppercase-label">{label}</span>
      <input
        id={id}
        aria-label={label}
        value={value}
        onChange={event => onChange(event.target.value)}
        placeholder={placeholder}
        className="t-input mt-2"
      />
    </label>
  )
}

function hasAction(task: AccountingReviewTask, action: AccountingReviewAction) {
  return task.candidate_actions.some(candidate => candidateAction(candidate) === action)
}

function AccountingTaskCard({
  task,
  rationale,
  details,
  onRationaleChange,
  onDetailsChange,
  onSubmit,
  submitting,
  submitError,
}: {
  task: AccountingReviewTask
  rationale: string
  details: AccountingDetailInputs
  onRationaleChange: (value: string) => void
  onDetailsChange: (patch: AccountingDetailInputs) => void
  onSubmit: (candidate: Record<string, unknown>) => void
  submitting: boolean
  submitError: string | null
}) {
  const needsInternalTransferDetails = hasAction(task, 'internal_transfer')
  const needsCostBasisDetails = hasAction(task, 'manual_cost_basis')

  return (
    <article data-testid={`accounting-task-${task.task_id}`} className="panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge-dim">{task.source}</span>
            <span className={severityBadge(task.severity)}>{fmtEnum(task.severity)}</span>
            <span className="badge-blue">{task.status}</span>
          </div>
          <h2 className="panel-title mt-3">{fmtEnum(task.task_type)}</h2>
          <p className="mt-1 font-mono text-xs text-dim">{task.task_id}</p>
        </div>
        <div className="grid min-w-[220px] grid-cols-3 gap-3 text-right">
          <div>
            <p className="uppercase-label">Asset</p>
            <p className="mt-1 font-mono text-sm text-bright">{task.asset_symbol}</p>
          </div>
          <div>
            <p className="uppercase-label">Amount</p>
            <p className="mt-1 font-mono text-sm text-bright">{fmtUsd(task.amount_usd)}</p>
          </div>
          <div>
            <p className="uppercase-label">Quantity</p>
            <p className="mt-1 font-mono text-sm text-bright">{fmtQuantity(task.quantity, task.asset_symbol)}</p>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 border-t border-[var(--line-1)] pt-4 lg:grid-cols-[1fr_1.2fr]">
        <div>
          <div className="panel-header">Accounting impact</div>
          <p className="mt-2 text-xs text-dim">
            Occurred {fmtDate(task.occurred_at)}. Resolve this task to update durable accounting state for the listed metric scopes.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {task.affected_metric_scopes.map(scope => (
              <span key={scope} className="badge-dim">{fmtScope(scope)}</span>
            ))}
          </div>
        </div>

        <div>
          <div className="panel-header">Evidence</div>
          <TaskEvidence task={task} />
        </div>
      </div>

      <div className="mt-4 border-t border-[var(--line-1)] pt-4">
        <label htmlFor={`rationale-${task.task_id}`} className="uppercase-label block">
          Rationale
        </label>
        <textarea
          id={`rationale-${task.task_id}`}
          aria-label={`Rationale for ${task.task_id}`}
          value={rationale}
          onChange={event => onRationaleChange(event.target.value)}
          className="t-input mt-2 min-h-[72px]"
          placeholder="Optional note for the accounting audit trail"
        />
      </div>

      {(needsInternalTransferDetails || needsCostBasisDetails) ? (
        <div className="mt-4 grid gap-4 border-t border-[var(--line-1)] pt-4 lg:grid-cols-2">
          {needsInternalTransferDetails ? (
            <div>
              <div className="panel-header">Internal transfer details</div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <DetailField
                  id={`to-source-${task.task_id}`}
                  label={`Destination source for ${task.task_id}`}
                  value={details.to_source ?? ''}
                  onChange={value => onDetailsChange({ to_source: value })}
                  placeholder="hyperliquid"
                />
                <DetailField
                  id={`to-evidence-key-${task.task_id}`}
                  label={`Destination evidence key for ${task.task_id}`}
                  value={details.to_evidence_key ?? ''}
                  onChange={value => onDetailsChange({ to_evidence_key: value })}
                  placeholder="destination event key"
                />
                <DetailField
                  id={`to-quantity-${task.task_id}`}
                  label={`Destination quantity for ${task.task_id}`}
                  value={details.to_quantity ?? ''}
                  onChange={value => onDetailsChange({ to_quantity: value })}
                  placeholder={String(task.quantity ?? '')}
                />
                <DetailField
                  id={`fee-quantity-${task.task_id}`}
                  label={`Fee quantity for ${task.task_id}`}
                  value={details.fee_quantity ?? ''}
                  onChange={value => onDetailsChange({ fee_quantity: value })}
                  placeholder="optional"
                />
                <DetailField
                  id={`fee-asset-${task.task_id}`}
                  label={`Fee asset for ${task.task_id}`}
                  value={details.fee_asset_symbol ?? ''}
                  onChange={value => onDetailsChange({ fee_asset_symbol: value })}
                  placeholder={task.asset_symbol}
                />
              </div>
            </div>
          ) : null}

          {needsCostBasisDetails ? (
            <div>
              <div className="panel-header">Manual cost basis details</div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <DetailField
                  id={`basis-quantity-${task.task_id}`}
                  label={`Basis quantity for ${task.task_id}`}
                  value={details.basis_quantity ?? ''}
                  onChange={value => onDetailsChange({ basis_quantity: value })}
                  placeholder={String(task.quantity ?? '')}
                />
                <DetailField
                  id={`basis-total-${task.task_id}`}
                  label={`Total cost basis USD for ${task.task_id}`}
                  value={details.cost_basis_usd ?? ''}
                  onChange={value => onDetailsChange({ cost_basis_usd: value })}
                  placeholder="3250"
                />
                <DetailField
                  id={`basis-unit-${task.task_id}`}
                  label={`Unit cost USD for ${task.task_id}`}
                  value={details.unit_cost_usd ?? ''}
                  onChange={value => onDetailsChange({ unit_cost_usd: value })}
                  placeholder="optional"
                />
                <DetailField
                  id={`basis-method-${task.task_id}`}
                  label={`Basis method for ${task.task_id}`}
                  value={details.basis_method ?? ''}
                  onChange={value => onDetailsChange({ basis_method: value })}
                  placeholder="manual_average"
                />
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {task.candidate_actions.map((candidate, index) => (
          <CandidateButton
            key={`${task.task_id}-${index}`}
            candidate={candidate}
            disabled={submitting}
            onSubmit={() => onSubmit(candidate)}
          />
        ))}
      </div>

      {submitting ? <p className="mt-3 text-xs text-dim">Submitting accounting decision...</p> : null}
      {submitError ? <div className="mt-3 text-xs val-neg">{submitError}</div> : null}
    </article>
  )
}

export default function AccountingReviewPage() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [queue, setQueue] = useState<AccountingReviewQueue | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState('')
  const [submitErrors, setSubmitErrors] = useState<Record<string, string>>({})
  const [successMessage, setSuccessMessage] = useState('')
  const [submitting, setSubmitting] = useState<string | null>(null)
  const [rationales, setRationales] = useState<Record<string, string>>({})
  const [detailsByTask, setDetailsByTask] = useState<Record<string, AccountingDetailInputs>>({})

  const loadTasks = useCallback(async () => {
    setLoading(true)
    setFetchError('')
    try {
      setQueue(await accountingReviewAPI.tasks())
    } catch (err: any) {
      setFetchError(err.message || 'Accounting review tasks are unavailable.')
      setQueue(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) {
      router.push('/login')
      return
    }
    loadTasks()
  }, [isAuthenticated, isLoading, loadTasks, router])

  async function submitDecision(task: AccountingReviewTask, candidate: Record<string, unknown>) {
    const action = candidateAction(candidate)
    const pendingKey = `${task.task_id}:${action ?? 'unknown'}`
    const payload = buildDecisionPayload(task, candidate, rationales[task.task_id] ?? '', detailsByTask[task.task_id] ?? {})

    setSubmitErrors(prev => ({ ...prev, [task.task_id]: '' }))
    setSuccessMessage('')

    if ('error' in payload) {
      setSubmitErrors(prev => ({ ...prev, [task.task_id]: payload.error }))
      return
    }

    setSubmitting(pendingKey)
    try {
      const response = await accountingReviewAPI.decide(payload)
      setSuccessMessage(`${response.task_id} resolved as ${response.decision_type}`)
      setRationales(prev => ({ ...prev, [task.task_id]: '' }))
      setDetailsByTask(prev => ({ ...prev, [task.task_id]: {} }))
      await loadTasks()
    } catch (err: any) {
      setSubmitErrors(prev => ({
        ...prev,
        [task.task_id]: err.message || 'Accounting decision could not be submitted.',
      }))
    } finally {
      setSubmitting(null)
    }
  }

  if (isLoading || !isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg)', fontFamily: 'monospace' }}>
        <span className="text-green text-sm">[ AUTH CHECK<span className="cursor">_</span> ]</span>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <Sidebar />

      <main className="px-4 pb-8 pt-[60px] md:ml-[220px] md:px-6 lg:px-8">
        <div className="mx-auto max-w-6xl space-y-4 py-8">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-bright text-xs uppercase">[ ACCOUNTING REVIEW ]</p>
              <h1 className="mt-2 text-xl font-semibold text-bright">Accounting review</h1>
              <p className="text-dim text-xs mt-1">
                Resolve reconciliation, import, and cost-basis tasks that affect portfolio truth.
              </p>
            </div>
            <button type="button" className="btn-ghost" onClick={loadTasks} disabled={loading}>
              Refresh
            </button>
          </div>

          {successMessage ? <div className="panel p-3 text-xs val-pos">{successMessage}</div> : null}

          {loading ? (
            <div className="panel p-8 text-center uppercase-label text-dim">Loading accounting tasks</div>
          ) : fetchError ? (
            <div className="panel p-6">
              <div className="panel-header">Blocked</div>
              <p className="mt-3 text-sm val-neg">{fetchError}</p>
              <button type="button" className="btn-ghost mt-4" onClick={loadTasks}>Retry</button>
            </div>
          ) : queue && queue.tasks.length === 0 ? (
            <div className="panel p-8 text-center">
              <div className="panel-header">No open tasks</div>
              <p className="mt-3 text-sm text-dim">No accounting tasks are open.</p>
            </div>
          ) : queue ? (
            <>
              <QueueSummary queue={queue} />
              <div className="space-y-3">
                {queue.tasks.map(task => (
                  <AccountingTaskCard
                    key={task.task_id}
                    task={task}
                    rationale={rationales[task.task_id] ?? ''}
                    details={detailsByTask[task.task_id] ?? {}}
                    onRationaleChange={value => setRationales(prev => ({ ...prev, [task.task_id]: value }))}
                    onDetailsChange={patch => setDetailsByTask(prev => ({
                      ...prev,
                      [task.task_id]: { ...(prev[task.task_id] ?? {}), ...patch },
                    }))}
                    onSubmit={candidate => submitDecision(task, candidate)}
                    submitting={submitting?.startsWith(`${task.task_id}:`) ?? false}
                    submitError={submitErrors[task.task_id] || null}
                  />
                ))}
              </div>
            </>
          ) : null}
        </div>
      </main>
    </div>
  )
}
