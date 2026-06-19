import { render, screen, waitFor } from '@testing-library/react'
import DashboardPage from '@/app/page'
import PortfolioDetailsPage from '@/app/portfolio/page'
import HoldingDetailPage from '@/app/holdings/[symbol]/page'
import { HoldingsPanel } from '@/components/dashboard/HoldingsPanel'
import { intelligenceAPI, portfolioAPI, syncAPI, watchlistAPI } from '@/lib/api'
import {
  dashboardAssetContributions,
  dashboardCapitalTruth,
  dashboardHoldings,
  dashboardPendingOrders,
  dashboardPerformanceSummary,
  dashboardSummary,
  dashboardSyncStatuses,
  dashboardTransactions,
} from './dashboard.fixtures'

const push = jest.fn()
const router = { push }
const pathname = jest.fn(() => '/')
const params = jest.fn(() => ({ symbol: 'BTC' }))
const searchParams = jest.fn(() => new URLSearchParams('institution=binance'))

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
  intelligenceAPI: {
    listNotes: jest.fn(),
    createNote: jest.fn(),
    updateNote: jest.fn(),
    deleteNote: jest.fn(),
    getClassification: jest.fn(),
    activity: jest.fn(),
  },
  watchlistAPI: {
    list: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    delete: jest.fn(),
    alertEvents: jest.fn(),
    evaluateAlerts: jest.fn(),
  },
}))

jest.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="responsive-container">{children}</div>,
  PieChart: ({ children }: { children: React.ReactNode }) => <svg data-testid="pie-chart">{children}</svg>,
  Pie: ({ children, data }: { children: React.ReactNode; data?: unknown[] }) => (
    <g data-testid="pie" data-points={JSON.stringify(data ?? [])}>{children}</g>
  ),
  Cell: ({ fill }: { fill?: string }) => <path data-testid="pie-cell" data-fill={fill ?? ''} />,
  Tooltip: () => null,
  AreaChart: ({ children, data }: { children: React.ReactNode; data?: unknown[] }) => (
    <svg data-testid="area-chart" data-points={JSON.stringify(data ?? [])}>{children}</svg>
  ),
  Area: ({ dataKey, stroke }: { dataKey?: string; stroke?: string }) => (
    <path data-testid="area-series" data-key={dataKey ?? ''} data-stroke={stroke ?? ''} />
  ),
  XAxis: ({ dataKey }: { dataKey?: string }) => <g data-testid="x-axis" data-key={dataKey ?? ''} />,
  Line: ({ dataKey, stroke }: { dataKey?: string; stroke?: string }) => (
    <path data-testid="line-series" data-key={dataKey ?? ''} data-stroke={stroke ?? ''} />
  ),
}))

function mobileSections(container: HTMLElement) {
  return Array.from(container.querySelectorAll('[data-mobile-section]')).map(element =>
    element.getAttribute('data-mobile-section')
  )
}

function mobileSectionForText(text: string | RegExp) {
  const element = screen.getByText(text)
  return element.closest('[data-mobile-section]')?.getAttribute('data-mobile-section')
}

function directMobileSectionChildren(container: HTMLElement, selector: string) {
  return Array.from(container.querySelector(selector)?.children ?? []).filter(child =>
    child.matches('[data-mobile-section]')
  )
}

describe('mobile-first route IA', () => {
  beforeEach(() => {
    push.mockReset()
    pathname.mockReturnValue('/')
    params.mockReturnValue({ symbol: 'BTC' })
    searchParams.mockReturnValue(new URLSearchParams('institution=binance'))
    jest.mocked(portfolioAPI.summary).mockResolvedValue(dashboardSummary)
    jest.mocked(portfolioAPI.capitalTruth).mockResolvedValue(dashboardCapitalTruth)
    jest.mocked(portfolioAPI.performanceSummary).mockResolvedValue(dashboardPerformanceSummary)
    jest.mocked(portfolioAPI.pendingOrders).mockResolvedValue(dashboardPendingOrders)
    jest.mocked(portfolioAPI.assetContributions).mockResolvedValue(dashboardAssetContributions)
    jest.mocked(portfolioAPI.transactions).mockResolvedValue(dashboardTransactions)
    jest.mocked(syncAPI.status).mockResolvedValue(dashboardSyncStatuses)
    jest.mocked(syncAPI.binance).mockResolvedValue({ synced: 0, skipped: 0, synced_at: new Date().toISOString() })
    jest.mocked(intelligenceAPI.listNotes).mockResolvedValue([{ id: 1, entity_type: 'portfolio', entity_id: 'portfolio', content: 'Review risk budget', user_id: 1, created_at: new Date().toISOString(), updated_at: null, deleted_at: null }])
    jest.mocked(intelligenceAPI.getClassification).mockResolvedValue({ symbol: 'BTC', sector: 'Crypto', asset_type: 'crypto', themes: ['Store of value'], thesis_status: 'core', tags: [] })
    jest.mocked(intelligenceAPI.activity).mockResolvedValue([{ id: 1, source: 'note', status: 'created', message: 'Note created', entity_type: 'portfolio', entity_id: 'portfolio', metadata: {}, created_at: new Date().toISOString() }])
    jest.mocked(intelligenceAPI.createNote).mockResolvedValue({ id: 2, entity_type: 'portfolio', entity_id: 'portfolio', content: 'New note', user_id: 1, created_at: new Date().toISOString(), updated_at: null, deleted_at: null })
    jest.mocked(intelligenceAPI.deleteNote).mockResolvedValue({ message: 'Deleted' })
    jest.mocked(watchlistAPI.list).mockResolvedValue([{ id: 1, symbol: 'MSFT', name: 'Microsoft', market: 'NASDAQ', asset_type: 'equity', priority: 'high', status: 'researching', target_entry_min: null, target_entry_max: 300, thesis: 'AI platform', catalyst: null, next_review_date: null, owned_asset_id: null, created_at: new Date().toISOString(), updated_at: null }])
    jest.mocked(watchlistAPI.alertEvents).mockResolvedValue([])
  })

  it('renders holdings as mobile cards instead of table-like compressed rows', () => {
    const { container } = render(<HoldingsPanel holdings={dashboardHoldings} />)

    expect(container.querySelector('.mobile-holding-columns')).toBeInTheDocument()
    expect(container.querySelectorAll('.mobile-holding-card')).toHaveLength(dashboardHoldings.length)
    expect(container.querySelector('table')).not.toBeInTheDocument()
  })

  it('preserves overview mobile order from summary through activity without unmarked visual surfaces', async () => {
    const { container } = render(<DashboardPage />)

    await screen.findByText('Total portfolio value')

    expect(mobileSections(container)).toEqual([
      'overview-summary',
      'overview-growth',
      'overview-asset-contributions',
      'overview-health',
      'overview-holdings',
      'overview-action-surfaces',
      'overview-activity',
    ])
    expect(mobileSectionForText('LIVE')).toBe('overview-health')
    expect(mobileSectionForText('Asset winners / losers')).toBe('overview-asset-contributions')
    expect(mobileSectionForText('Allocation')).toBe('overview-holdings')
  })

  it('keeps overview action and activity as side-by-side desktop siblings with no empty grid column', async () => {
    const { container } = render(<DashboardPage />)

    await screen.findByText('Total portfolio value')

    const overviewWorkflow = container.querySelector('[data-overview-workflow]')
    expect(overviewWorkflow).toHaveClass('xl:grid-cols-[0.85fr_1.15fr]')
    expect(directMobileSectionChildren(container, '[data-overview-workflow]')).toHaveLength(2)
  })

  it('preserves portfolio details mobile order and exposes filters as disabled placeholders', async () => {
    const { container } = render(<PortfolioDetailsPage />)

    await waitFor(() => expect(screen.getByText('Personal treasury review')).toBeInTheDocument())

    const portfolioFilter = screen.getByRole('button', { name: /portfolio filters unavailable/i })
    expect(portfolioFilter).toBeDisabled()
    expect(portfolioFilter).toHaveAttribute('aria-disabled', 'true')
    await waitFor(() => expect(container.querySelectorAll('.mobile-review-card').length).toBeGreaterThan(0))
    expect(mobileSectionForText('Important holdings')).toBe('portfolio-holdings')
    expect(mobileSectionForText('Non-owned ideas and target entries')).toBe('portfolio-action-surfaces')
    expect(directMobileSectionChildren(container, '[data-portfolio-workflow]')).toHaveLength(2)
    expect(mobileSections(container)).toEqual([
      'portfolio-summary',
      'portfolio-health',
      'portfolio-holdings',
      'portfolio-action-surfaces',
      'portfolio-activity',
    ])
  })

  it('preserves holding detail mobile order and exposes filters as disabled placeholders', async () => {
    const { container } = render(<HoldingDetailPage />)

    await waitFor(() => expect(screen.getByText('Asset detail · v1')).toBeInTheDocument())

    const holdingFilter = screen.getByRole('button', { name: /holding activity filters unavailable/i })
    expect(holdingFilter).toBeDisabled()
    expect(holdingFilter).toHaveAttribute('aria-disabled', 'true')
    expect(mobileSections(container)).toEqual([
      'holding-summary',
      'holding-health',
      'holding-holdings',
      'holding-action-surfaces',
      'holding-activity',
    ])
  })
})
