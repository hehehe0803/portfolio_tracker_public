const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function request<T>(
  path: string,
  options: RequestInit & { requireAuth?: boolean; accessToken?: string } = {}
): Promise<T> {
  const { requireAuth = true, accessToken, ...init } = options
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string>),
  }
  if (requireAuth) {
    const token = accessToken ?? (typeof window !== 'undefined' ? localStorage.getItem('access_token') : null)
    if (token) headers['Authorization'] = `Bearer ${token}`
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(err.detail || 'Request failed')
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  totp_required: boolean
}

export interface MeResponse {
  id: number
  username: string
  totp_enabled: boolean
  telegram_configured: boolean
}

export const authAPI = {
  login: (username: string, password: string, totp_code?: string) =>
    request<LoginResponse>('/v1/auth/login', {
      method: 'POST',
      requireAuth: false,
      body: JSON.stringify({ username, password, totp_code }),
    }),

  me: (accessToken?: string) => request<MeResponse>('/v1/auth/me', { accessToken }),

  totpSetup: () =>
    request<{ secret: string; qr_code_base64: string; uri: string }>('/v1/auth/totp/setup', {
      method: 'POST',
    }),

  totpVerify: (code: string) =>
    request<{ message: string }>('/v1/auth/totp/verify', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  totpDisable: (code: string) =>
    request<{ message: string }>('/v1/auth/totp/disable', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  changePassword: (current_password: string, new_password: string) =>
    request<{ message: string }>('/v1/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),
}

// ── Portfolio ────────────────────────────────────────────────────────────────

export interface FreshnessMetadata {
  source: string
  as_of: string | null
  stale: boolean
  degraded: boolean
  fallback: boolean
  warnings: string[]
}

export interface Holding {
  symbol: string
  asset_type: string
  institution: string
  quantity: number
  avg_buy_price_usd: number | null
  current_price_usd: number | null
  current_value_usd: number | null
  total_cost_usd: number
  unrealized_pnl_usd: number | null
  unrealized_pnl_pct: number | null
  freshness?: FreshnessMetadata
}

export interface BenchmarkRatios {
  spx_in_btc: number | null
  spx_in_gold: number | null
}

export interface PortfolioSummary {
  total_value_usd: number
  total_cost_usd: number
  total_pnl_usd: number
  total_pnl_pct: number
  holding_count: number
  by_asset_type: Record<string, number>
  benchmarks: BenchmarkRatios
  holdings: Holding[]
}

export interface Transaction {
  id: number
  institution: string
  type: string
  asset: string
  asset_type: string
  quantity: number
  price_usd: number | null
  total_usd: number | null
  fee: number
  fee_currency: string
  timestamp: string
  raw_data?: Record<string, string | number | null>
}

export interface PerformanceScope {
  gross_deposits_usd?: number | null
  gross_withdrawals_usd?: number | null
  net_invested_capital_usd?: number | null
  bridge_transfer_in_usd?: number | null
  bridge_transfer_out_usd?: number | null
  reward_income_usd?: number | null
  fees_usd?: number | null
  realized_pnl_usd?: number | null
  unrealized_pnl_usd?: number | null
  total_pnl_usd?: number | null
  total_cost_usd?: number | null
  current_value_usd?: number | null
  xirr?: number | null
  [key: string]: number | null | undefined
}

export interface CapitalFlowAuditRow {
  transaction_id: number
  timestamp: string
  institution: string
  tx_type: string
  asset_symbol: string
  economic_category: string
  amount_usd: number | null
  included_in_capital_totals: boolean
  exclusion_reason: string | null
}

export interface CapitalTruthSummary {
  money_in_usd: number
  money_out_usd: number
  net_capital_in_usd: number
  current_value_usd: number
  lifetime_pnl_usd: number
  lifetime_return_pct: number | null
  current_value_source: string
  warnings: string[]
  excluded_row_count: number
  unclassified_transfer_count: number
  capital_flow_audit: CapitalFlowAuditRow[]
}

export interface PerformanceSummary {
  institutions: Record<string, PerformanceScope>
  combined: PerformanceScope
  comparisons: Record<string, Record<string, number | null | undefined>>
}

export interface PendingOrder {
  institution: string
  symbol: string
  external_order_id: string
  order_type: string
  status: string
  side: string
  quantity: number
  limit_price: number | null
  stop_price: number | null
  placed_at: string | null
}

export interface AssetContribution {
  symbol: string
  asset_type: string
  institution: string
  institutions: string[]
  quantity: number
  total_cost_usd: number
  current_value_usd: number
  realized_pnl_usd: number
  unrealized_pnl_usd: number
  reward_income_usd: number
  fees_usd: number
  net_lifetime_pnl_usd: number
}

export interface AssetContributionSummary {
  assets: AssetContribution[]
  totals: {
    current_value_usd: number
    realized_pnl_usd: number
    unrealized_pnl_usd: number
    reward_income_usd: number
    fees_usd: number
    net_lifetime_pnl_usd: number
  }
  sort: {
    sort_by: string
    order: 'asc' | 'desc' | string
  }
}

export const portfolioAPI = {
  summary: () => request<PortfolioSummary>('/v1/portfolio/summary'),
  capitalTruth: () => request<CapitalTruthSummary>('/v1/portfolio/capital-truth'),
  performanceSummary: () => request<PerformanceSummary>('/v1/portfolio/performance-summary'),
  pendingOrders: () => request<PendingOrder[]>('/v1/portfolio/pending-orders'),
  assetContributions: (params?: { sort_by?: string; order?: 'asc' | 'desc' }) => {
    const q = new URLSearchParams()
    if (params?.sort_by) q.set('sort_by', params.sort_by)
    if (params?.order) q.set('order', params.order)
    const suffix = q.toString() ? `?${q}` : ''
    return request<AssetContributionSummary>(`/v1/portfolio/asset-contributions${suffix}`)
  },
  transactions: (params?: { institution?: string; asset?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams()
    if (params?.institution) q.set('institution', params.institution)
    if (params?.asset) q.set('asset', params.asset)
    if (params?.limit) q.set('limit', String(params.limit))
    if (params?.offset) q.set('offset', String(params.offset))
    return request<Transaction[]>(`/v1/portfolio/transactions?${q}`)
  },
}

// ── Intelligence ──────────────────────────────────────────────────────────────

export type EntityType = 'portfolio' | 'asset' | 'watchlist' | 'system'

export interface Note {
  id: number
  entity_type: EntityType
  entity_id: string
  content: string
  user_id: number
  created_at: string
  updated_at: string | null
  deleted_at: string | null
}

export interface Tag {
  id: number
  name: string
  color: string
  icon: string | null
  created_at: string
}

export interface ActivityEvent {
  id: number
  source: string
  status: string
  message: string
  entity_type: string | null
  entity_id: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface AssetClassification {
  symbol: string
  sector: string | null
  asset_type: string
  themes: string[]
  thesis_status: string
  tags: Tag[]
}

export const intelligenceAPI = {
  listNotes: (params?: { entity_type?: EntityType; entity_id?: string; include_deleted?: boolean }) => {
    const q = new URLSearchParams()
    if (params?.entity_type) q.set('entity_type', params.entity_type)
    if (params?.entity_id) q.set('entity_id', params.entity_id)
    if (params?.include_deleted) q.set('include_deleted', 'true')
    const suffix = q.toString() ? `?${q}` : ''
    return request<Note[]>(`/v1/intelligence/notes${suffix}`)
  },
  createNote: (data: { entity_type: EntityType; entity_id: string; content: string }) =>
    request<Note>('/v1/intelligence/notes', { method: 'POST', body: JSON.stringify(data) }),
  updateNote: (id: number, content: string) =>
    request<Note>(`/v1/intelligence/notes/${id}`, { method: 'PATCH', body: JSON.stringify({ content }) }),
  deleteNote: (id: number) => request<{ message: string }>(`/v1/intelligence/notes/${id}`, { method: 'DELETE' }),
  listTags: () => request<Tag[]>('/v1/intelligence/tags'),
  createTag: (data: { name: string; color?: string; icon?: string | null }) =>
    request<Tag>('/v1/intelligence/tags', { method: 'POST', body: JSON.stringify(data) }),
  updateTag: (id: number, data: { name: string; color?: string; icon?: string | null }) =>
    request<Tag>(`/v1/intelligence/tags/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteTag: (id: number) => request<{ message: string }>(`/v1/intelligence/tags/${id}`, { method: 'DELETE' }),
  getClassification: (symbol: string) => request<AssetClassification>(`/v1/intelligence/assets/${encodeURIComponent(symbol)}/classification`),
  updateClassification: (symbol: string, data: { sector?: string | null; asset_type: string; themes?: string[]; thesis_status: string }) =>
    request<AssetClassification>(`/v1/intelligence/assets/${encodeURIComponent(symbol)}/classification`, { method: 'PUT', body: JSON.stringify(data) }),
  assignAssetTag: (symbol: string, tagId: number) =>
    request<{ message: string }>(`/v1/intelligence/assets/${encodeURIComponent(symbol)}/tags/${tagId}`, { method: 'POST' }),
  removeAssetTag: (symbol: string, tagId: number) =>
    request<{ message: string }>(`/v1/intelligence/assets/${encodeURIComponent(symbol)}/tags/${tagId}`, { method: 'DELETE' }),
  activity: (params?: { entity_type?: EntityType | string; entity_id?: string; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.entity_type) q.set('entity_type', params.entity_type)
    if (params?.entity_id) q.set('entity_id', params.entity_id)
    if (params?.limit) q.set('limit', String(params.limit))
    const suffix = q.toString() ? `?${q}` : ''
    return request<ActivityEvent[]>(`/v1/intelligence/activity${suffix}`)
  },
}

// ── Review queue ─────────────────────────────────────────────────────────────

export type ReviewDecisionAction = 'hold' | 'add' | 'trim' | 'exit' | 'research' | 'snooze' | 'archive'

export interface ReviewQueueItem {
  key: string
  entity_type: EntityType
  entity_id: string
  title: string
  reasons: string[]
  priority: 'low' | 'medium' | 'high' | string
  metadata: Record<string, unknown>
}

export interface ReviewQueueResponse {
  as_of: string
  allowed_decisions: ReviewDecisionAction[]
  items: ReviewQueueItem[]
}

export interface ReviewDecision {
  id: number
  entity_type: EntityType
  entity_id: string
  decision: ReviewDecisionAction
  rationale: string | null
  next_review_date: string | null
  created_at: string
}

export const reviewAPI = {
  queue: (params?: { stale_note_days?: number; major_pnl_pct?: number; event_lookback_days?: number }) => {
    const q = new URLSearchParams()
    if (params?.stale_note_days) q.set('stale_note_days', String(params.stale_note_days))
    if (params?.major_pnl_pct != null) q.set('major_pnl_pct', String(params.major_pnl_pct))
    if (params?.event_lookback_days) q.set('event_lookback_days', String(params.event_lookback_days))
    const suffix = q.toString() ? `?${q}` : ''
    return request<ReviewQueueResponse>(`/v1/review/queue${suffix}`)
  },
  decide: (data: { entity_type: EntityType; entity_id: string; decision: ReviewDecisionAction; rationale?: string | null; next_review_date?: string | null }) =>
    request<ReviewDecision>('/v1/review/decisions', { method: 'POST', body: JSON.stringify(data) }),
  decisions: (params?: { entity_type?: EntityType; entity_id?: string; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.entity_type) q.set('entity_type', params.entity_type)
    if (params?.entity_id) q.set('entity_id', params.entity_id)
    if (params?.limit) q.set('limit', String(params.limit))
    const suffix = q.toString() ? `?${q}` : ''
    return request<ReviewDecision[]>(`/v1/review/decisions${suffix}`)
  },
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

export const accountingReviewAPI = {
  tasks: () => request<AccountingReviewQueue>('/v1/review/accounting/tasks'),
  decide: (data: AccountingReviewDecisionRequest) =>
    request<AccountingReviewDecisionResponse>('/v1/review/accounting/decisions', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

// ── Watchlist ─────────────────────────────────────────────────────────────────

export interface WatchlistItem {
  id: number
  symbol: string
  name: string | null
  market: string | null
  asset_type: string
  priority: 'low' | 'medium' | 'high' | string
  status: 'idea' | 'researching' | 'ready' | 'paused' | 'promoted' | 'archived' | string
  target_entry_min: number | null
  target_entry_max: number | null
  thesis: string | null
  catalyst: string | null
  next_review_date: string | null
  owned_asset_id: number | null
  created_at: string
  updated_at: string | null
  current_price_usd?: number | null
  freshness?: FreshnessMetadata
}

export interface WatchlistTargetAlert {
  id: number
  watchlist_item_id: number
  trigger_price: number
  target_entry_max: number
  message: string
  telegram_delivered: boolean
  delivered_at: string | null
  triggered_at: string
}

export type WatchlistPayload = Omit<WatchlistItem, 'id' | 'created_at' | 'updated_at'>

export const watchlistAPI = {
  list: (params?: { status?: string; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.limit) q.set('limit', String(params.limit))
    const suffix = q.toString() ? `?${q}` : ''
    return request<WatchlistItem[]>(`/v1/watchlist${suffix}`)
  },
  get: (id: number) => request<WatchlistItem>(`/v1/watchlist/${id}`),
  create: (data: WatchlistPayload) => request<WatchlistItem>('/v1/watchlist', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: WatchlistPayload) => request<WatchlistItem>(`/v1/watchlist/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: number) => request<{ message: string }>(`/v1/watchlist/${id}`, { method: 'DELETE' }),
  promote: (id: number, symbol: string) => request<WatchlistItem>(`/v1/watchlist/${id}/promote/${encodeURIComponent(symbol)}`, { method: 'POST' }),
  evaluateAlerts: () => request<{ triggered: Array<{ watchlist_item_id: number; symbol: string; trigger_price: number; target_entry_max: number }> }>('/v1/watchlist/alerts/evaluate', { method: 'POST' }),
  alertEvents: () => request<WatchlistTargetAlert[]>('/v1/watchlist/alerts/events'),
}

// ── Sync ─────────────────────────────────────────────────────────────────────

export interface SyncStatus {
  name: string
  last_sync_at: string | null
  degraded: boolean
  warning: string | null
  note: string | null
}

export interface FreshnessSection {
  enabled: boolean
  cadence_seconds: number
  last_success_at: string | null
  last_failure_at: string | null
  last_failure: string | null
  stale: boolean
  next_run_at: string | null
  last_degraded_at?: string | null
}

export interface SyncFreshness {
  owned_polling: FreshnessSection
  binance_auto_sync: FreshnessSection
}

export const syncAPI = {
  binance: () => request<{ synced: number; skipped: number; synced_at?: string; error?: string }>('/v1/sync/binance', { method: 'POST' }),
  status: () => request<SyncStatus[]>('/v1/sync/status'),
  freshness: () => request<SyncFreshness>('/v1/sync/freshness'),
}

// ── Imports ──────────────────────────────────────────────────────────────────

export interface ImportArtifact {
  id: number
  institution: string
  filename: string
  status: string
  parsed_count: number
  committed_count: number
  duplicate_count: number
  preview?: {
    total_parsed: number
    new: number
    duplicates: number
    sample: Array<{ date: string; type: string; symbol: string; amount: number | null; description: string }>
  }
  error?: string
  created_at: string
  committed_at: string | null
}

export const importsAPI = {
  uploadXtb: async (file: File) => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${API_BASE}/v1/imports/xtb`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(err.detail || 'Upload failed')
    }
    return res.json()
  },

  uploadBinance: async (file: File) => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${API_BASE}/v1/imports/binance`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(err.detail || 'Upload failed')
    }
    return res.json()
  },

  confirm: (id: number) =>
    request<{ committed: number; duplicates_skipped: number }>(`/v1/imports/${id}/confirm`, { method: 'POST' }),

  list: () => request<ImportArtifact[]>('/v1/imports/'),

  get: (id: number) => request<ImportArtifact>(`/v1/imports/${id}`),
}

// ── Alerts ───────────────────────────────────────────────────────────────────

export const alertsAPI = {
  listRules: () =>
    request<Array<{ id: number; asset_symbol: string; condition: string; threshold: number; is_active: boolean; created_at: string }>>('/v1/alerts/rules'),

  createRule: (data: { asset_symbol: string; condition: string; threshold: number }) =>
    request<{ id: number; message: string }>('/v1/alerts/rules', { method: 'POST', body: JSON.stringify(data) }),

  deleteRule: (id: number) => request<{ message: string }>(`/v1/alerts/rules/${id}`, { method: 'DELETE' }),

  toggleRule: (id: number) => request<{ is_active: boolean }>(`/v1/alerts/rules/${id}/toggle`, { method: 'PATCH' }),

  events: () =>
    request<Array<{ id: number; rule_id: number; message: string; telegram_delivered: boolean; triggered_at: string }>>('/v1/alerts/events'),
}

// ── Settings ─────────────────────────────────────────────────────────────────

export const settingsAPI = {
  setBinanceKeys: (api_key: string, api_secret: string) =>
    request<{ message: string }>('/v1/settings/binance-keys', {
      method: 'POST',
      body: JSON.stringify({ api_key, api_secret }),
    }),

  setTelegram: (chat_id: string) =>
    request<{ message: string }>('/v1/settings/telegram', {
      method: 'POST',
      body: JSON.stringify({ chat_id }),
    }),
}
