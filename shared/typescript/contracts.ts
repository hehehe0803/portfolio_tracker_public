export interface AssetSnapshot {
  symbol: string
  asset_type: string
  institution: string
  quantity: string
  avg_buy_price_usd?: string | null
  current_price_usd?: string | null
  current_value_usd?: string | null
  total_cost_usd?: string | null
  unrealized_pnl_usd?: string | null
  unrealized_pnl_pct?: string | null
}

export interface TransactionRecord {
  institution: string
  tx_type: string
  asset_symbol: string
  asset_type: string
  quantity: string
  timestamp: string
  fingerprint: string
  price_usd?: string | null
  total_usd?: string | null
  fee?: string
  fee_currency?: string
}

export interface ImportArtifactContract {
  institution: string
  filename: string
  file_type: string
  status: string
  parsed_count: number
  committed_count: number
  duplicate_count: number
  created_at?: string | null
}

export interface AlertRuleContract {
  asset_symbol: string
  condition: string
  threshold: string
  is_active: boolean
}

export interface AlertEventContract {
  rule_id: number
  message: string
  telegram_delivered: boolean
  triggered_at?: string | null
  delivered_at?: string | null
}

export interface TagContract {
  name: string
  color: string
  icon?: string | null
}

export interface NoteContract {
  entity_type: string
  entity_id: string
  content: string
  created_at?: string | null
}

export interface IngestionEvent {
  source: string
  artifact_id?: number | null
  status: string
  message?: string | null
  created_at?: string | null
}

export type AccountingReviewAction =
  | 'internal_transfer'
  | 'personal_withdrawal'
  | 'import_approval'
  | 'manual_cost_basis'
  | 'unknown_cost_basis'
  | 'unknown'

export interface AccountingReviewTask {
  task_id: string
  task_type: string
  status: string
  severity: string
  source: string
  asset_symbol: string
  quantity?: string | null
  amount_usd?: string | null
  occurred_at: string
  evidence: Record<string, unknown>
  candidate_actions: Array<Record<string, unknown>>
  affected_metric_scopes: string[]
  created_at?: string | null
}

export interface AccountingReviewQueue {
  review_type: 'accounting'
  allowed_actions: AccountingReviewAction[]
  tasks: AccountingReviewTask[]
}

export interface InternalTransferDecision {
  to_source: string
  to_evidence_key: string
  to_quantity: string
  fee_quantity?: string | null
  fee_asset_symbol?: string | null
}

export interface ManualCostBasisDecision {
  quantity?: string | null
  cost_basis_usd?: string | null
  unit_cost_usd?: string | null
  basis_method?: string | null
}

export interface AccountingReviewDecisionRequest {
  task_id: string
  action: AccountingReviewAction
  idempotency_key: string
  rationale?: string | null
  internal_transfer?: InternalTransferDecision | null
  cost_basis?: ManualCostBasisDecision | null
}

export interface AccountingReviewDecisionResponse {
  task_id: string
  task_status: 'resolved'
  decision_type: string
  decision_id: number
  replayed: boolean
}
