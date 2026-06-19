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
    jest.mocked(portfolioAPI.summary).mockReset()
    jest.mocked(portfolioAPI.capitalTruth).mockReset()
    jest.mocked(portfolioAPI.performanceSummary).mockReset()
    jest.mocked(portfolioAPI.pendingOrders).mockReset()
    jest.mocked(portfolioAPI.assetContributions).mockReset()
    jest.mocked(portfolioAPI.transactions).mockReset()
    jest.mocked(syncAPI.binance).mockReset()
    jest.mocked(syncAPI.status).mockReset()

    jest.mocked(portfolioAPI.capitalTruth).mockResolvedValue(dashboardCapitalTruth)
    jest.mocked(portfolioAPI.performanceSummary).mockResolvedValue(dashboardPerformanceSummary)
    jest.mocked(portfolioAPI.assetContributions).mockResolvedValue(dashboardAssetContributions)
    jest.mocked(portfolioAPI.pendingOrders).mockResolvedValue(dashboardPendingOrders)
    jest.mocked(syncAPI.status).mockResolvedValue(dashboardSyncStatuses)
  })

  it('renders the authenticated loading state', () => {
    const summaryRequest = deferred<typeof dashboardSummary>()
    const transactionRequest = deferred<typeof dashboardTransactions>()
    jest.mocked(portfolioAPI.summary).mockReturnValue(summaryRequest.promise)
    jest.mocked(portfolioAPI.transactions).mockReturnValue(transactionRequest.promise)

    render(<DashboardPage />)

    expect(screen.getByText('Loading telemetry')).toBeInTheDocument()
  })

  it('renders an error banner when dashboard data fails to load', async () => {
    jest.mocked(portfolioAPI.summary).mockRejectedValue(new Error('portfolio unavailable'))
    jest.mocked(portfolioAPI.transactions).mockRejectedValue(new Error('transaction feed unavailable'))

    render(<DashboardPage />)

    await waitFor(() => {
      expect(screen.getByText('portfolio unavailable')).toBeInTheDocument()
    })

    expect(screen.queryByText('Loading telemetry')).not.toBeInTheDocument()
  })

  it('renders the loaded dashboard with fixture-backed data', async () => {
    jest.mocked(portfolioAPI.summary).mockResolvedValue(dashboardSummary)
    jest.mocked(portfolioAPI.transactions).mockResolvedValue(dashboardTransactions)

    const { container } = render(<DashboardPage />)

    await screen.findByText('Total portfolio value')
    await screen.findByText('Portfolio growth')

    expect(jest.mocked(portfolioAPI.capitalTruth)).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Lifetime P/L')).toBeInTheDocument()
    expect(screen.getByText('-$6.4K')).toBeInTheDocument()
    expect(screen.getByText('-16.54%')).toBeInTheDocument()
    expect(screen.getByText('Net capital in')).toBeInTheDocument()
    expect(screen.getByText('$39.0K')).toBeInTheDocument()
    expect(screen.getByText('Deposits - withdrawals vs current value. Excludes rows flagged incomplete.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ALL' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'YTD' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1Y' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '3M' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1M' })).toBeInTheDocument()
    expect(screen.getByTestId('area-chart').getAttribute('data-points')).toContain('netCapitalIn')
    expect(screen.getAllByTestId('line-series').some(el => el.getAttribute('data-key') === 'netCapitalIn')).toBe(true)

    expect(jest.mocked(portfolioAPI.transactions)).toHaveBeenCalledWith({
      limit: 50,
      offset: 0,
    })
    expect(screen.getByText('Total portfolio value')).toBeInTheDocument()
    expect(screen.getAllByText(/59,510/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Holdings').length).toBeGreaterThan(0)
    expect(screen.getByText('Recent activity')).toBeInTheDocument()
    expect(screen.getByText('Allocation')).toBeInTheDocument()
    expect(screen.getByText('Portfolio growth')).toBeInTheDocument()
    await screen.findByText('Asset winners / losers')
    expect(jest.mocked(portfolioAPI.assetContributions)).toHaveBeenCalledWith({
      sort_by: 'net_lifetime_pnl_usd',
      order: 'desc',
    })
    expect(screen.getByText('Biggest winners')).toBeInTheDocument()
    expect(screen.getByText('Biggest losers')).toBeInTheDocument()
    expect(screen.getByText('LUNA')).toBeInTheDocument()
    expect(screen.getByText('-$5.4K')).toBeInTheDocument()
    expect(screen.getByText('realized -$5.4K')).toBeInTheDocument()
    expect(screen.getByText('fees -$18.00')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '$ P/L' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '% return' })).toBeInTheDocument()
    expect(screen.getByText('Pending orders')).toBeInTheDocument()
    expect(screen.getByText('Institution sync state')).toBeInTheDocument()
    expect(screen.getAllByText(/degraded/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText('withdraw_history: withdraw disabled').length).toBeGreaterThan(0)
    expect(screen.getAllByText('BTC').length).toBeGreaterThan(0)
    expect(screen.getAllByText('AAPL').length).toBeGreaterThan(0)
    expect(screen.getByTestId('area-chart').getAttribute('data-points')).toContain('2026-04-03')
    expect(screen.getByTestId('pie').getAttribute('data-points')).toContain('crypto')
    expect(screen.queryByText('Loading telemetry')).not.toBeInTheDocument()

    expect(container.querySelector('main')).toMatchSnapshot()
  })

  it('loads only a small recent transaction feed for the dashboard', async () => {
    jest.mocked(portfolioAPI.summary).mockResolvedValue(dashboardSummary)
    jest.mocked(portfolioAPI.transactions).mockResolvedValue(dashboardTransactions)

    render(<DashboardPage />)

    await screen.findByText('Total portfolio value')
    expect(jest.mocked(portfolioAPI.transactions)).toHaveBeenCalledTimes(1)
    expect(jest.mocked(portfolioAPI.transactions)).toHaveBeenCalledWith({
      limit: 50,
      offset: 0,
    })
  })

  it('paints core dashboard content before slow background panels finish', async () => {
    const txRequest = deferred<typeof dashboardTransactions>()
    const perfRequest = deferred<typeof dashboardPerformanceSummary>()
    const ordersRequest = deferred<typeof dashboardPendingOrders>()
    jest.mocked(portfolioAPI.summary).mockResolvedValue(dashboardSummary)
    jest.mocked(syncAPI.status).mockResolvedValue(dashboardSyncStatuses)
    jest.mocked(portfolioAPI.transactions).mockReturnValue(txRequest.promise)
    jest.mocked(portfolioAPI.performanceSummary).mockReturnValue(perfRequest.promise)
    jest.mocked(portfolioAPI.pendingOrders).mockReturnValue(ordersRequest.promise)

    render(<DashboardPage />)

    expect(await screen.findByText('Total portfolio value')).toBeInTheDocument()
    expect(screen.queryByText('Loading telemetry')).not.toBeInTheDocument()
    expect(screen.getByText('Performance data unavailable')).toBeInTheDocument()

    txRequest.resolve(dashboardTransactions)
    perfRequest.resolve(dashboardPerformanceSummary)
    ordersRequest.resolve(dashboardPendingOrders)
  })

  it('keeps the core dashboard visible when optional portfolio surface requests fail', async () => {
    jest.mocked(portfolioAPI.summary).mockResolvedValue(dashboardSummary)
    jest.mocked(portfolioAPI.transactions).mockResolvedValue(dashboardTransactions)
    jest.mocked(portfolioAPI.performanceSummary).mockRejectedValue(new Error('performance summary unavailable'))
    jest.mocked(portfolioAPI.pendingOrders).mockRejectedValue(new Error('pending orders unavailable'))
    jest.mocked(portfolioAPI.assetContributions).mockRejectedValue(new Error('asset contributions unavailable'))
    jest.mocked(syncAPI.status).mockRejectedValue(new Error('sync status unavailable'))

    render(<DashboardPage />)

    await screen.findByText('Total portfolio value')

    await waitFor(() => {
      expect(screen.getByText('Performance summary is unavailable right now.')).toBeInTheDocument()
    })
    expect(screen.getByText('Asset winners/losers are temporarily unavailable.')).toBeInTheDocument()
    expect(screen.getByText('Pending orders are temporarily unavailable.')).toBeInTheDocument()
    expect(screen.getByText('Institution sync status is temporarily unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('No open or pending orders are currently tracked.')).not.toBeInTheDocument()
    expect(screen.queryByText('No institution sync channels are configured yet.')).not.toBeInTheDocument()
  })

  it('syncs Binance and refreshes the loaded dashboard', async () => {
    const user = userEvent.setup()
    jest.mocked(portfolioAPI.summary)
      .mockResolvedValueOnce(dashboardSummary)
      .mockResolvedValueOnce({
        ...dashboardSummary,
        total_pnl_usd: 17000,
        total_pnl_pct: 40.0,
      })
    jest.mocked(portfolioAPI.transactions)
      .mockResolvedValueOnce(dashboardTransactions)
      .mockResolvedValueOnce(dashboardTransactions)
    jest.mocked(syncAPI.binance).mockResolvedValue({ synced: 2, skipped: 0 })

    render(<DashboardPage />)

    await screen.findByText('Total portfolio value')
    await user.click(screen.getByRole('button', { name: 'Sync Binance' }))

    await waitFor(() => {
      expect(syncAPI.binance).toHaveBeenCalledTimes(1)
    })

    expect(screen.getByText('Synced 2 records')).toBeInTheDocument()
    expect(screen.getByText('Total portfolio value')).toBeInTheDocument()
    expect(screen.getAllByText('BTC').length).toBeGreaterThan(0)
  })

  it('opens mobile navigation with access to dashboard sections', async () => {
    const user = userEvent.setup()
    jest.mocked(portfolioAPI.summary).mockResolvedValue(dashboardSummary)
    jest.mocked(portfolioAPI.transactions).mockResolvedValue(dashboardTransactions)

    render(<DashboardPage />)

    await screen.findByText('Total portfolio value')
    await user.click(screen.getByRole('button', { name: 'Open navigation menu' }))

    expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Transactions' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Import' })).toBeInTheDocument()
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
