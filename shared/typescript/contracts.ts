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
