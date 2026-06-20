import { render, screen, waitFor, within } from '@testing-library/react'
import HoldingDetailPage from '@/app/holdings/[symbol]/page'
import { intelligenceAPI, portfolioAPI } from '@/lib/api'
import type { AccountingReviewTask, AssetDetailContract } from '../../shared/typescript/contracts'

const push = jest.fn()
const router = { push }
const params = jest.fn(() => ({ symbol: 'BTC' }))
const searchParams = jest.fn(() => new URLSearchParams('institution=binance'))
const pathname = jest.fn(() => '/holdings/BTC')

jest.mock('next/navigation', () => ({
  useRouter: () => router,
  usePathname: () => pathname(),
  useParams: () => params(),
  useSearchParams: () => searchParams(),
}))

jest.mock('@/components/providers/auth-provider', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { username: 'operator' },
    logout: jest.fn(),
  }),
}))

jest.mock('@/components/intelligence/NotePanel', () => ({
  NotePanel: ({ title }: { title: string }) => <div data-testid="note-panel">{title}</div>,
}))

jest.mock('@/lib/api', () => ({
  portfolioAPI: {
    assetDetail: jest.fn(),
    summary: jest.fn(),
    transactions: jest.fn(),
    pendingOrders: jest.fn(),
  },
  intelligenceAPI: {
    getClassification: jest.fn(),
    activity: jest.fn(),
  },
}))

const blockingTask: AccountingReviewTask = {
  task_id: 'acct-missing-cost-basis-btc',
  task_type: 'missing_cost_basis',
  status: 'open',
  severity: 'severe',
  source: 'binance',
  asset_symbol: 'BTC',
  quantity: '0.10',
  amount_usd: '1800',
  occurred_at: '2026-04-12T09:00:00+00:00',
  evidence: {
    reason: 'Missing acquisition cost basis for part of the current BTC lot.',
  },
  candidate_actions: [
    {
      action: 'manual_cost_basis',
      label: 'Enter confirmed BTC cost basis',
    },
  ],
  affected_metric_scopes: ['asset_level_lifetime_pnl', 'current_position_pnl'],
  created_at: '2026-04-12T09:05:00+00:00',
}

const trustedAssetDetail: AssetDetailContract = {
  symbol: 'BTC',
  asset_type: 'crypto',
  as_of: '2026-04-14T10:00:00+00:00',
  current_position: {
    quantity: '0.1',
    current_price_usd: '70000',
    current_value_usd: '7000',
    average_cost_usd: '50000',
    current_position_pnl_usd: '2000',
    current_position_pnl_pct: '40',
    confidence_state: 'trusted',
    reason_codes: [],
  },
  capital_allocated_usd: '5000',
  lifetime: {
    contribution_basis_usd: '3200',
    contribution_pnl_usd: '2800',
    confidence_state: 'trusted',
    reason_codes: [],
    visible: true,
  },
  recent_movement: {
    period_label: '30D',
    movement_usd: '3000',
    direction: 'positive',
    confidence_state: 'trusted',
    reason_codes: [],
    value_state: 'visible',
  },
  driver_explanation: {
    symbol: 'BTC',
    period_label: '30D',
    movement_usd: '3000',
    share_of_known_movement_pct: '75',
    direction: 'positive',
    explanation: 'BTC gained $3000 over 30D after external flows.',
    confidence_state: 'trusted',
    reason_codes: [],
  },
  trust_blockers: [],
}

const blockedAssetDetail: AssetDetailContract = {
  ...trustedAssetDetail,
  current_position: {
    ...trustedAssetDetail.current_position,
    current_position_pnl_usd: null,
    current_position_pnl_pct: null,
    confidence_state: 'blocked',
    reason_codes: ['missing_cost_basis'],
  },
  lifetime: {
    ...trustedAssetDetail.lifetime,
    contribution_pnl_usd: null,
    confidence_state: 'blocked',
    reason_codes: ['missing_cost_basis'],
    visible: false,
  },
  trust_blockers: [blockingTask],
}

const provisionalLifetimeAssetDetail: AssetDetailContract = {
  ...trustedAssetDetail,
  lifetime: {
    contribution_basis_usd: null,
    contribution_pnl_usd: null,
    confidence_state: 'provisional',
    reason_codes: ['missing_asset_lifetime_contribution_data'],
    visible: false,
  },
}

const partialCurrentPositionPnlAssetDetail: AssetDetailContract = {
  ...trustedAssetDetail,
  current_position: {
    ...trustedAssetDetail.current_position,
    current_position_pnl_usd: '2000',
    current_position_pnl_pct: null,
    confidence_state: 'trusted',
    reason_codes: [],
  },
}

describe('asset detail UI', () => {
  beforeEach(() => {
    push.mockReset()
    params.mockReturnValue({ symbol: 'BTC' })
    searchParams.mockReturnValue(new URLSearchParams('institution=binance'))
    pathname.mockReturnValue('/holdings/BTC')
    jest.mocked(portfolioAPI.assetDetail).mockReset()
    jest.mocked(portfolioAPI.summary).mockReset()
    jest.mocked(portfolioAPI.transactions).mockReset()
    jest.mocked(portfolioAPI.pendingOrders).mockReset()
    jest.mocked(intelligenceAPI.getClassification).mockReset()
    jest.mocked(intelligenceAPI.activity).mockReset()

    jest.mocked(portfolioAPI.assetDetail).mockResolvedValue(trustedAssetDetail)
    jest.mocked(portfolioAPI.summary).mockResolvedValue({
      total_value_usd: 7000,
      total_cost_usd: 5000,
      total_pnl_usd: 2000,
      total_pnl_pct: 40,
      holding_count: 1,
      by_asset_type: { crypto: 7000 },
      benchmarks: { spx_in_btc: null, spx_in_gold: null },
      holdings: [
        {
          symbol: 'BTC',
          asset_type: 'crypto',
          institution: 'binance',
          quantity: 0.1,
          avg_buy_price_usd: 50000,
          current_price_usd: 70000,
          current_value_usd: 7000,
          total_cost_usd: 5000,
          unrealized_pnl_usd: 2000,
          unrealized_pnl_pct: 40,
        },
      ],
    })
    jest.mocked(portfolioAPI.transactions).mockResolvedValue([])
    jest.mocked(portfolioAPI.pendingOrders).mockResolvedValue([])
    jest.mocked(intelligenceAPI.getClassification).mockResolvedValue({
      symbol: 'BTC',
      sector: 'Crypto',
      asset_type: 'crypto',
      themes: [],
      thesis_status: 'none',
      tags: [],
    })
    jest.mocked(intelligenceAPI.activity).mockResolvedValue([])
  })

  it('loads the VNEXT asset-detail contract and labels current-position P&L separately', async () => {
    render(<HoldingDetailPage />)

    await screen.findByText('Current-position P&L')

    expect(jest.mocked(portfolioAPI.assetDetail)).toHaveBeenCalledWith('BTC')
    const pnlCard = screen.getByTestId('current-position-pnl')
    expect(within(pnlCard).getByText('$2,000.00')).toBeInTheDocument()
    expect(within(pnlCard).getByText('+40.00%')).toBeInTheDocument()
    expect(within(pnlCard).queryByText(/lifetime|contribution/i)).not.toBeInTheDocument()
    expect(screen.queryByText('Unrealized')).not.toBeInTheDocument()
  })

  it('keeps lifetime contribution state separate from current-position P&L', async () => {
    render(<HoldingDetailPage />)

    await screen.findByText('Lifetime contribution P&L')

    const lifetimeCard = screen.getByTestId('lifetime-contribution')
    expect(screen.getByText('Capital allocated')).toBeInTheDocument()
    expect(screen.getByText('$5,000.00')).toBeInTheDocument()
    expect(within(lifetimeCard).getByText('$3,200.00')).toBeInTheDocument()
    expect(within(lifetimeCard).getByText('$2,800.00')).toBeInTheDocument()
    expect(within(lifetimeCard).queryByText('$2,000.00')).not.toBeInTheDocument()
    expect(screen.getByText('BTC gained $3000 over 30D after external flows.')).toBeInTheDocument()
  })

  it('blocks sensitive lifetime contribution values and shows trust blockers', async () => {
    jest.mocked(portfolioAPI.assetDetail).mockResolvedValue(blockedAssetDetail)

    render(<HoldingDetailPage />)

    await screen.findByText('Lifetime contribution P&L')

    const lifetimeCard = screen.getByTestId('lifetime-contribution')
    expect(within(lifetimeCard).getByText(/blocked until accounting review resolves/i)).toBeInTheDocument()
    expect(within(lifetimeCard).queryByText('$2,800.00')).not.toBeInTheDocument()
    expect(screen.getByText('Trust blockers')).toBeInTheDocument()
    expect(screen.getByText('missing cost basis')).toBeInTheDocument()
    expect(screen.getByText(/Missing acquisition cost basis/)).toBeInTheDocument()
  })

  it('keeps raw activity and import logs collapsed behind a drilldown', async () => {
    render(<HoldingDetailPage />)

    await screen.findByText('Raw activity and import logs')

    const drilldown = screen.getByTestId('raw-asset-drilldowns')
    expect(drilldown.tagName).toBe('DETAILS')
    expect(drilldown).not.toHaveAttribute('open')
  })

  it('does not render synthetic asset truth when the contract fails to load', async () => {
    jest.mocked(portfolioAPI.assetDetail).mockRejectedValue(new Error('asset position not found'))

    render(<HoldingDetailPage />)

    await screen.findByText('asset position not found')

    expect(screen.queryByText('Current position')).not.toBeInTheDocument()
    expect(screen.queryByText('Lifetime contribution P&L')).not.toBeInTheDocument()
    expect(screen.queryByText('No material asset-level accounting blockers.')).not.toBeInTheDocument()
  })

  it('distinguishes provisional hidden lifetime data from blocked accounting state', async () => {
    jest.mocked(portfolioAPI.assetDetail).mockResolvedValue(provisionalLifetimeAssetDetail)

    render(<HoldingDetailPage />)

    await screen.findByText('Lifetime contribution P&L')

    const lifetimeCard = screen.getByTestId('lifetime-contribution')
    expect(within(lifetimeCard).getAllByText('Unavailable').length).toBeGreaterThan(0)
    expect(within(lifetimeCard).getByText(/Unavailable while missing asset lifetime contribution data remains provisional/i)).toBeInTheDocument()
    expect(within(lifetimeCard).queryByText(/Blocked until accounting review resolves/i)).not.toBeInTheDocument()
    expect(within(lifetimeCard).queryByText(/confidence is blocked/i)).not.toBeInTheDocument()
  })

  it('shows current-position P&L dollars when only the percent is unavailable', async () => {
    jest.mocked(portfolioAPI.assetDetail).mockResolvedValue(partialCurrentPositionPnlAssetDetail)

    render(<HoldingDetailPage />)

    await screen.findByText('Current-position P&L')

    const pnlCard = screen.getByTestId('current-position-pnl')
    expect(within(pnlCard).getByText('$2,000.00')).toBeInTheDocument()
    expect(within(pnlCard).getByText('Percent unavailable')).toBeInTheDocument()
    expect(within(pnlCard).queryByText('Blocked')).not.toBeInTheDocument()
  })
})
