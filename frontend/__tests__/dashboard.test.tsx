import userEvent from '@testing-library/user-event'
import { render, screen, waitFor, within } from '@testing-library/react'
import { ActivityFeed } from '@/components/dashboard/ActivityFeed'
import { AllocationPanel } from '@/components/dashboard/AllocationPanel'
import { HoldingsPanel } from '@/components/dashboard/HoldingsPanel'
import { PendingOrdersPanel } from '@/components/dashboard/PendingOrdersPanel'
import { PerformanceSummaryPanel } from '@/components/dashboard/PerformanceSummaryPanel'
import { PortfolioChart, reconstructPortfolioHistory } from '@/components/dashboard/PortfolioChart'
import { StatCard } from '@/components/dashboard/StatCard'
import { SyncStatusPanel } from '@/components/dashboard/SyncStatusPanel'
import DashboardPage from '@/app/page'
import { portfolioAPI, syncAPI } from '@/lib/api'
import {
  dashboardAssetContributions,
  dashboardCapitalTruth,
  dashboardHoldings,
  dashboardPendingOrders,
  dashboardPerformanceSummary,
  dashboardSummary,
  dashboardSyncStatuses,
  dashboardTransactions,
  fixedNow,
  severeBlockedDashboardContract,
  trustedDashboardContract,
} from './dashboard.fixtures'

const push = jest.fn()
const router = { push }
const RealDate = Date

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

class MockDate extends RealDate {
  constructor(value?: string | number | Date) {
    if (arguments.length === 0) {
      super(fixedNow)
      return
    }
    if (value === undefined) {
      super(fixedNow)
      return
    }
    super(value instanceof RealDate ? value.getTime() : value)
  }

  static now() {
    return fixedNow.getTime()
  }
}

jest.mock('next/navigation', () => ({
  useRouter: () => router,
  usePathname: () => '/',
}))

jest.mock('@/components/providers/auth-provider', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { username: 'operator' },
    logout: jest.fn(),
  }),
}))

jest.mock('@/lib/api', () => ({
  portfolioAPI: {
    dashboard: jest.fn(),
    summary: jest.fn(),
    capitalTruth: jest.fn(),
    performanceSummary: jest.fn(),
    pendingOrders: jest.fn(),
    assetContributions: jest.fn(),
    transactions: jest.fn(),
  },
  syncAPI: {
    binance: jest.fn(),
    status: jest.fn(),
  },
  watchlistAPI: {
    list: jest.fn().mockResolvedValue([]),
  },
}))

jest.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="responsive-container">{children}</div>,
  PieChart: ({ children }: { children: React.ReactNode }) => <svg data-testid="pie-chart">{children}</svg>,
  Pie: ({ children, data }: { children: React.ReactNode; data?: unknown[] }) => (
    <g data-testid="pie" data-points={JSON.stringify(data ?? [])}>
      {children}
    </g>
  ),
  Cell: ({ fill }: { fill?: string }) => <path data-testid="pie-cell" data-fill={fill ?? ''} />,
  Tooltip: () => null,
  AreaChart: ({ children, data }: { children: React.ReactNode; data?: unknown[] }) => (
    <svg data-testid="area-chart" data-points={JSON.stringify(data ?? [])}>
      {children}
    </svg>
  ),
  Area: ({ dataKey, stroke }: { dataKey?: string; stroke?: string }) => (
    <path data-testid="area-series" data-key={dataKey ?? ''} data-stroke={stroke ?? ''} />
  ),
  XAxis: ({ dataKey }: { dataKey?: string }) => <g data-testid="x-axis" data-key={dataKey ?? ''} />,
  Line: ({ dataKey, stroke }: { dataKey?: string; stroke?: string }) => (
    <path data-testid="line-series" data-key={dataKey ?? ''} data-stroke={stroke ?? ''} />
  ),
}))

describe('dashboard UI', () => {
  beforeAll(() => {
    // Freeze dates so the dashboard timestamp and relative chart output are stable.
    global.Date = MockDate as unknown as DateConstructor
  })

  afterAll(() => {
    global.Date = RealDate
  })

  beforeEach(() => {
    push.mockReset()
    jest.mocked(portfolioAPI.dashboard).mockReset()
    jest.mocked(portfolioAPI.summary).mockReset()
    jest.mocked(portfolioAPI.capitalTruth).mockReset()
    jest.mocked(portfolioAPI.performanceSummary).mockReset()
    jest.mocked(portfolioAPI.pendingOrders).mockReset()
    jest.mocked(portfolioAPI.assetContributions).mockReset()
    jest.mocked(portfolioAPI.transactions).mockReset()
    jest.mocked(syncAPI.binance).mockReset()
    jest.mocked(syncAPI.status).mockReset()

    jest.mocked(portfolioAPI.dashboard).mockResolvedValue(trustedDashboardContract)
    jest.mocked(portfolioAPI.capitalTruth).mockResolvedValue(dashboardCapitalTruth)
    jest.mocked(portfolioAPI.performanceSummary).mockResolvedValue(dashboardPerformanceSummary)
    jest.mocked(portfolioAPI.assetContributions).mockResolvedValue(dashboardAssetContributions)
    jest.mocked(portfolioAPI.pendingOrders).mockResolvedValue(dashboardPendingOrders)
    jest.mocked(syncAPI.status).mockResolvedValue(dashboardSyncStatuses)
  })

  it('renders the authenticated loading state', () => {
    const dashboardRequest = deferred<typeof trustedDashboardContract>()
    jest.mocked(portfolioAPI.dashboard).mockReturnValue(dashboardRequest.promise)

    render(<DashboardPage />)

    expect(screen.getByText('Loading dashboard')).toBeInTheDocument()
  })

  it('renders an error banner when dashboard data fails to load', async () => {
    jest.mocked(portfolioAPI.dashboard).mockRejectedValue(new Error('dashboard unavailable'))

    render(<DashboardPage />)

    await waitFor(() => {
      expect(screen.getByText('dashboard unavailable')).toBeInTheDocument()
    })

    expect(screen.queryByText('Loading dashboard')).not.toBeInTheDocument()
  })

  it('VNEXT-07B renders trusted dashboard contract as the first screen', async () => {
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue(trustedDashboardContract)

    render(<DashboardPage />)

    await waitFor(() => {
      expect(jest.mocked(portfolioAPI.dashboard)).toHaveBeenCalledTimes(1)
    })

    expect(await screen.findByText('Current total value')).toBeInTheDocument()
    const bridge = screen.getByTestId('dashboard-value-bridge')
    expect(bridge.compareDocumentPosition(screen.getByText('Current total value'))).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(within(bridge).getByText('30D value bridge')).toBeInTheDocument()
    expect(within(bridge).getByText('Starting value')).toBeInTheDocument()
    expect(within(bridge).getByText('$53,000.00')).toBeInTheDocument()
    expect(within(bridge).getByText('Investment gain')).toBeInTheDocument()
    expect(screen.getAllByText('$59,510.38').length).toBeGreaterThan(0)
    expect(screen.getByText('30D investment gain')).toBeInTheDocument()
    expect(screen.getAllByText('+$5,010.38').length).toBeGreaterThan(0)
    expect(screen.getAllByText('External contributions').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$2,000.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('External withdrawals').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$500.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Net capital at work').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$44,000.00').length).toBeGreaterThan(0)
    expect(screen.getByText('Lifetime P/L')).toBeInTheDocument()
    expect(screen.getByText('+$15,510.38')).toBeInTheDocument()
    expect(screen.getAllByText('Trusted').length).toBeGreaterThan(0)
    expect(screen.getByText('Asset-type distribution')).toBeInTheDocument()
    expect(screen.getByText('Crypto')).toBeInTheDocument()
    expect(screen.getByText('$40,000.00')).toBeInTheDocument()
    expect(screen.getByText('67.2%')).toBeInTheDocument()
    expect(screen.getByText('Cash reserve')).toBeInTheDocument()
    expect(screen.getAllByText('$8,500.00').length).toBeGreaterThan(0)
    expect(screen.getByText('Stablecoin reserve')).toBeInTheDocument()
    expect(screen.getByText('$6,000.00')).toBeInTheDocument()
    expect(screen.getByText('Holding drivers')).toBeInTheDocument()
    expect(screen.getAllByText('BTC').length).toBeGreaterThan(0)
    expect(screen.getByText('+$3,100.00')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.getByText('-$275.00')).toBeInTheDocument()
    expect(screen.getByText('No accounting action needed.')).toBeInTheDocument()
    expect(screen.getByText('Raw activity and import logs')).toBeInTheDocument()
  })

  it('VNEXT-07B suppresses sensitive values and promotes reconciliation when confidence is blocked', async () => {
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue(severeBlockedDashboardContract)

    render(<DashboardPage />)

    expect(await screen.findByText('Current total value')).toBeInTheDocument()
    expect(screen.getAllByText('$59,510.38').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Blocked').length).toBeGreaterThan(0)
    expect(screen.getAllByText('missing cost basis').length).toBeGreaterThan(0)
    expect(screen.getByText('30D investment gain unavailable')).toBeInTheDocument()
    expect(screen.getByText('Lifetime P/L unavailable')).toBeInTheDocument()
    expect(screen.getByText('Resolve missing cost basis')).toBeInTheDocument()
    expect(screen.getAllByText('BTC').length).toBeGreaterThan(0)
    expect(screen.getByText('$1,200.00')).toBeInTheDocument()
    expect(screen.getByText('period performance')).toBeInTheDocument()
    expect(screen.queryByText('+$5,010.38')).not.toBeInTheDocument()
    expect(screen.queryByText('+$15,510.38')).not.toBeInTheDocument()
  })

  it('VNEXT-07B hides net capital when the contract blocks net capital scope', async () => {
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue({
      ...trustedDashboardContract,
      blocked_metric_scopes: ['net_capital'],
      confidence_state: 'blocked',
      reason_codes: ['unresolved_cashflow'],
      lifetime: {
        ...trustedDashboardContract.lifetime,
        confidence_state: 'blocked',
        reason_codes: ['unresolved_cashflow'],
      },
    })

    render(<DashboardPage />)

    expect(await screen.findByText('Current total value')).toBeInTheDocument()
    expect(screen.getAllByText('Net capital unavailable')).toHaveLength(2)
    expect(screen.queryByText('$44,000.00')).not.toBeInTheDocument()
    expect(screen.getAllByText('Review required').length).toBeGreaterThan(0)
  })

  it('VNEXT-07B marks flagged holding drivers without rendering exact movement values', async () => {
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue({
      ...trustedDashboardContract,
      holding_drivers: [
        {
          ...trustedDashboardContract.holding_drivers[0],
          confidence_state: 'provisional',
          reason_codes: ['missing_price_anchor'],
          value_state: 'flagged',
        },
      ],
    })

    render(<DashboardPage />)

    expect(await screen.findByText('Holding drivers')).toBeInTheDocument()
    expect(screen.getByText('Flagged for review')).toBeInTheDocument()
    expect(screen.getByText('missing price anchor')).toBeInTheDocument()
    expect(screen.queryByText('+$3,100.00')).not.toBeInTheDocument()
    expect(screen.queryByText('61.9% of known move')).not.toBeInTheDocument()
  })

  it('VNEXT-07B hides distribution bar magnitude when percentage is suppressed', async () => {
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue({
      ...trustedDashboardContract,
      asset_type_distribution: [
        {
          ...trustedDashboardContract.asset_type_distribution[0],
          percentage: null,
          percentage_state: 'suppressed',
          confidence_state: 'provisional',
          reason_codes: ['weak_denominator'],
        },
      ],
    })

    render(<DashboardPage />)

    expect(await screen.findByText('Asset-type distribution')).toBeInTheDocument()
    expect(screen.getByText('Hidden')).toBeInTheDocument()
    expect(screen.getByTestId('distribution-bar-crypto')).toHaveStyle({ width: '0%' })
  })

  it('VNEXT-07B does not render ambiguous legacy profit labels', async () => {
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue(trustedDashboardContract)

    render(<DashboardPage />)

    expect(await screen.findByText('Current total value')).toBeInTheDocument()
    expect(screen.queryByText(/all-time p[&/]l/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/^total p[&/]l$/i)).not.toBeInTheDocument()
  })

  it('renders the loaded dashboard from the contract without legacy portfolio surfaces', async () => {
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue(trustedDashboardContract)

    render(<DashboardPage />)

    expect(await screen.findByText('Current total value')).toBeInTheDocument()
    expect(jest.mocked(portfolioAPI.dashboard)).toHaveBeenCalledTimes(1)
    expect(jest.mocked(portfolioAPI.summary)).not.toHaveBeenCalled()
    expect(jest.mocked(portfolioAPI.capitalTruth)).not.toHaveBeenCalled()
    expect(jest.mocked(portfolioAPI.performanceSummary)).not.toHaveBeenCalled()
    expect(jest.mocked(portfolioAPI.assetContributions)).not.toHaveBeenCalled()
    expect(jest.mocked(portfolioAPI.transactions)).not.toHaveBeenCalled()
    expect(screen.queryByText('Recent activity')).not.toBeInTheDocument()
    expect(screen.queryByText('Asset winners / losers')).not.toBeInTheDocument()
    expect(screen.queryByText('Portfolio growth')).not.toBeInTheDocument()
  })

  it('keeps the contract dashboard visible when sync status is unavailable', async () => {
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue(trustedDashboardContract)
    jest.mocked(syncAPI.status).mockRejectedValue(new Error('sync status unavailable'))

    render(<DashboardPage />)

    expect(await screen.findByText('Current total value')).toBeInTheDocument()
    expect(screen.getAllByText('Sync status unavailable').length).toBeGreaterThan(0)
  })

  it('syncs Binance and refreshes the loaded dashboard', async () => {
    const user = userEvent.setup()
    jest.mocked(portfolioAPI.dashboard)
      .mockResolvedValueOnce(trustedDashboardContract)
      .mockResolvedValueOnce({
        ...trustedDashboardContract,
        current_total_value_usd: '60000.00',
      })
    jest.mocked(syncAPI.binance).mockResolvedValue({ synced: 2, skipped: 0 })

    render(<DashboardPage />)

    await screen.findByText('Current total value')
    await user.click(screen.getByRole('button', { name: 'Sync Binance' }))

    await waitFor(() => {
      expect(syncAPI.binance).toHaveBeenCalledTimes(1)
    })

    expect(screen.getByText('Synced 2 records')).toBeInTheDocument()
    expect(screen.getByText('$60,000.00')).toBeInTheDocument()
    expect(screen.getAllByText('BTC').length).toBeGreaterThan(0)
  })

  it('opens mobile navigation with access to dashboard sections', async () => {
    const user = userEvent.setup()
    jest.mocked(portfolioAPI.dashboard).mockResolvedValue(trustedDashboardContract)

    render(<DashboardPage />)

    await screen.findByText('Current total value')
    await user.click(screen.getByRole('button', { name: 'Open navigation menu' }))

    expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Transactions' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: 'Import' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: 'Settings' }).length).toBeGreaterThan(0)
  })

  it('snapshots the stat card widget', () => {
    const { container } = render(
      <StatCard
        label="Total Value"
        value="$59,510.38"
        sub="+$16,965.38 (+39.87%)"
        subColor="pos"
        accent="green"
      />,
    )

    expect(container).toMatchSnapshot()
  })

  it('snapshots the holdings panel widget', () => {
    const { container } = render(<HoldingsPanel holdings={dashboardHoldings} />)

    expect(container).toMatchSnapshot()
  })

  it('renders current holding values only with freshness metadata or warning', () => {
    render(
      <HoldingsPanel
        holdings={[
          {
            ...dashboardHoldings[0],
            freshness: {
              source: 'live_price_provider',
              as_of: '2026-04-14T10:00:00Z',
              stale: false,
              degraded: false,
              fallback: false,
              warnings: [],
            },
          },
          {
            ...dashboardHoldings[1],
            current_price_usd: null,
            current_value_usd: null,
            freshness: {
              source: 'missing_price',
              as_of: '2026-04-14T10:00:00Z',
              stale: true,
              degraded: true,
              fallback: false,
              warnings: ['AAPL has no current price metadata'],
            },
          },
        ]}
      />
    )

    expect(screen.getByText('fresh · live_price_provider')).toBeInTheDocument()
    expect(screen.getByText('AAPL has no current price metadata')).toBeInTheDocument()
    expect(screen.getByLabelText('AAPL current value unavailable: AAPL has no current price metadata')).toBeInTheDocument()
  })

  it('snapshots the allocation panel widget', () => {
    const { container } = render(<AllocationPanel byAssetType={dashboardSummary.by_asset_type} />)

    expect(container).toMatchSnapshot()
  })

  it('updates the allocation callout from mouse and keyboard-accessible category controls', async () => {
    const user = userEvent.setup()
    render(<AllocationPanel byAssetType={dashboardSummary.by_asset_type} />)

    const equityButton = screen.getByRole('button', { name: /Equity: \$2K, 3\.9 percent/i })
    await user.click(equityButton)

    expect(equityButton).toHaveAttribute('aria-pressed', 'true')
    expect(within(screen.getByTestId('allocation-callout')).getByText('Equity')).toBeInTheDocument()
    expect(within(screen.getByTestId('allocation-callout')).getByText(/3\.9\s*% of portfolio/)).toBeInTheDocument()

    const etfButton = screen.getByRole('button', { name: /Etf: \$3K, 5\.3 percent/i })
    await user.tab()

    expect(etfButton).toHaveFocus()
    expect(etfButton).toHaveAttribute('aria-pressed', 'true')
    expect(within(etfButton).getByText('Etf')).toBeInTheDocument()
    expect(within(screen.getByTestId('allocation-callout')).getByText(/5\.3\s*% of portfolio/)).toBeInTheDocument()
  })

  it('snapshots the activity feed widget', () => {
    const { container } = render(<ActivityFeed transactions={dashboardTransactions} />)

    expect(container).toMatchSnapshot()
  })

  it('snapshots the performance summary widget', () => {
    const { container } = render(<PerformanceSummaryPanel summary={dashboardPerformanceSummary} />)

    expect(container).toMatchSnapshot()
  })

  it('snapshots the pending orders widget', () => {
    const { container } = render(<PendingOrdersPanel orders={dashboardPendingOrders} />)

    expect(container).toMatchSnapshot()
  })

  it('snapshots the sync status widget', () => {
    const { container } = render(<SyncStatusPanel statuses={dashboardSyncStatuses} />)

    expect(container).toMatchSnapshot()
  })

  it('reconstructs portfolio history with stock split transactions', () => {
    const points = reconstructPortfolioHistory(
      [
        {
          symbol: 'XLU.US',
          asset_type: 'equity',
          institution: 'xtb',
          quantity: 12,
          avg_buy_price_usd: 43.085,
          current_price_usd: 46.16,
          current_value_usd: 553.92,
          total_cost_usd: 517.02,
          unrealized_pnl_usd: 36.9,
          unrealized_pnl_pct: 7.14,
        },
      ],
      [
        {
          id: 1,
          institution: 'xtb',
          type: 'buy',
          asset: 'XLU.US',
          asset_type: 'equity',
          quantity: 6,
          price_usd: 86.17,
          total_usd: -517.02,
          fee: 0,
          fee_currency: 'USD',
          timestamp: '2025-09-25T00:00:00Z',
        },
        {
          id: 2,
          institution: 'xtb',
          type: 'split',
          asset: 'XLU.US',
          asset_type: 'equity',
          quantity: 2,
          price_usd: null,
          total_usd: null,
          fee: 0,
          fee_currency: 'USD',
          timestamp: '2025-09-26T00:00:00Z',
        },
      ],
    )

    expect(points).toEqual([
      { date: '2025-09-25', value: 553.92 },
      { date: '2025-09-26', value: 553.92 },
    ])
  })

  it('uses id as a tiebreaker for same-timestamp chart transactions', () => {
    const points = reconstructPortfolioHistory(
      [
        {
          symbol: 'XLU.US',
          asset_type: 'equity',
          institution: 'xtb',
          quantity: 12,
          avg_buy_price_usd: 43.085,
          current_price_usd: 46.16,
          current_value_usd: 553.92,
          total_cost_usd: 517.02,
          unrealized_pnl_usd: 36.9,
          unrealized_pnl_pct: 7.14,
        },
      ],
      [
        {
          id: 2,
          institution: 'xtb',
          type: 'split',
          asset: 'XLU.US',
          asset_type: 'equity',
          quantity: 2,
          price_usd: null,
          total_usd: null,
          fee: 0,
          fee_currency: 'USD',
          timestamp: '2025-09-26T00:00:00Z',
        },
        {
          id: 1,
          institution: 'xtb',
          type: 'buy',
          asset: 'XLU.US',
          asset_type: 'equity',
          quantity: 6,
          price_usd: 86.17,
          total_usd: -517.02,
          fee: 0,
          fee_currency: 'USD',
          timestamp: '2025-09-26T00:00:00Z',
        },
      ],
    )

    expect(points).toEqual([{ date: '2025-09-26', value: 553.92 }])
  })

  it('reconstructs portfolio history through staking asset transformations', () => {
    const points = reconstructPortfolioHistory(
      [
        {
          symbol: 'WBETH',
          asset_type: 'crypto',
          institution: 'binance',
          quantity: 0.95,
          avg_buy_price_usd: 2105.26,
          current_price_usd: 2200,
          current_value_usd: 2090,
          total_cost_usd: 2000,
          unrealized_pnl_usd: 90,
          unrealized_pnl_pct: 4.5,
        },
      ],
      [
        {
          id: 1,
          institution: 'binance',
          type: 'buy',
          asset: 'BETH',
          asset_type: 'crypto',
          quantity: 1,
          price_usd: 2000,
          total_usd: 2000,
          fee: 0,
          fee_currency: 'USD',
          timestamp: '2026-01-01T00:00:00Z',
          raw_data: {},
        },
        {
          id: 2,
          institution: 'binance',
          type: 'staking_subscribe',
          asset: 'WBETH',
          asset_type: 'crypto',
          quantity: 0.95,
          price_usd: null,
          total_usd: null,
          fee: 0,
          fee_currency: 'USD',
          timestamp: '2026-01-02T00:00:00Z',
          raw_data: {
            stake_asset: 'BETH',
            stake_amount: 1,
          },
        },
      ],
    )

    expect(points).toEqual([
      { date: '2026-01-02', value: 2090 },
    ])
  })

  it('snapshots the portfolio chart widget', () => {
    const { container } = render(<PortfolioChart holdings={dashboardHoldings} transactions={dashboardTransactions} />)

    expect(container).toMatchSnapshot()
  })
})
