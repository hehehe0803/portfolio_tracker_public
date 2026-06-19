import userEvent from '@testing-library/user-event'
import { render, screen, waitFor, within } from '@testing-library/react'
import AccountingReviewPage from '@/app/review/page'
import { accountingReviewAPI, type AccountingReviewQueue } from '@/lib/api'

const push = jest.fn()
const router = { push }

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

jest.mock('next/navigation', () => ({
  useRouter: () => router,
  usePathname: () => '/review',
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
  accountingReviewAPI: {
    tasks: jest.fn(),
    decide: jest.fn(),
  },
}))

const accountingQueue: AccountingReviewQueue = {
  review_type: 'accounting' as const,
  allowed_actions: [
    'internal_transfer',
    'personal_withdrawal',
    'import_approval',
    'manual_cost_basis',
    'unknown_cost_basis',
    'unknown',
  ],
  tasks: [
    {
      task_id: 'task_binance_usdt_out_001',
      task_type: 'unknown_outgoing_transfer',
      status: 'open',
      severity: 'review_required',
      source: 'binance',
      asset_symbol: 'USDT',
      quantity: '500',
      amount_usd: '500',
      occurred_at: '2026-06-19T08:10:00Z',
      evidence: {
        source_evidence_key: 'binance-withdrawal-500-usdt',
        reasons: ['unknown_outgoing_crypto'],
        counterparty: '0xabc123',
      },
      candidate_actions: [
        {
          action: 'internal_transfer',
          label: 'Mark as internal transfer',
          effect: 'keeps external capital unchanged',
        },
        {
          action: 'personal_withdrawal',
          label: 'Classify as personal withdrawal',
          confidence: 'low',
          effect: 'reduces net capital at work',
        },
        {
          action: 'unknown',
          label: 'Keep unresolved for now',
          confidence: 'low',
          effect: 'leaves affected metrics blocked',
        },
      ],
      affected_metric_scopes: ['net_capital', 'lifetime_pnl'],
      created_at: '2026-06-19T08:12:00Z',
    },
    {
      task_id: 'task_sol_basis_001',
      task_type: 'missing_cost_basis',
      status: 'open',
      severity: 'blocked',
      source: 'binance',
      asset_symbol: 'SOL',
      quantity: '25',
      amount_usd: null,
      occurred_at: '2026-06-18T09:00:00Z',
      evidence: {
        reasons: ['missing_trade_import'],
      },
      candidate_actions: [
        {
          action: 'import_approval',
          label: 'Import missing source data',
          confidence: 'review_required',
          effect: 'may restore basis evidence',
        },
        {
          action: 'manual_cost_basis',
          label: 'Enter manual cost basis',
          effect: 'uses entered basis for affected scopes',
        },
        {
          action: 'unknown_cost_basis',
          label: 'Mark basis unknown',
          effect: 'keeps cost basis dependent metrics unavailable',
        },
      ],
      affected_metric_scopes: ['asset_lifetime_pnl', 'cost_basis'],
      created_at: '2026-06-18T09:05:00Z',
    },
  ],
}

describe('AccountingReviewPage', () => {
  beforeEach(() => {
    push.mockReset()
    jest.mocked(accountingReviewAPI.tasks).mockReset()
    jest.mocked(accountingReviewAPI.decide).mockReset()
    jest.mocked(accountingReviewAPI.tasks).mockResolvedValue(accountingQueue)
    jest.mocked(accountingReviewAPI.decide).mockResolvedValue({
      task_id: 'task_binance_usdt_out_001',
      task_status: 'resolved',
      decision_type: 'accounting_transfer_link',
      decision_id: 42,
      replayed: false,
    })
  })

  it('renders accounting tasks with confidence, materiality, evidence, and backend choices', async () => {
    render(<AccountingReviewPage />)

    expect(await screen.findByText('Accounting review')).toBeInTheDocument()
    expect(screen.getByText('2 open accounting tasks')).toBeInTheDocument()
    expect(screen.getByText('Blocked tasks')).toBeInTheDocument()
    expect(screen.getAllByText('USDT').length).toBeGreaterThan(0)
    expect(screen.getByText('UNKNOWN OUTGOING TRANSFER')).toBeInTheDocument()
    expect(screen.getByText('$500.00')).toBeInTheDocument()
    expect(screen.getByText('500 USDT')).toBeInTheDocument()
    expect(screen.getByText('REVIEW REQUIRED')).toBeInTheDocument()
    expect(screen.getByText('NET CAPITAL')).toBeInTheDocument()
    expect(screen.getByText('LIFETIME PNL')).toBeInTheDocument()
    expect(screen.getByText('source_evidence_key: binance-withdrawal-500-usdt')).toBeInTheDocument()
    expect(screen.getByLabelText(/destination source for task_binance_usdt_out_001/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/destination evidence key for task_binance_usdt_out_001/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/destination quantity for task_binance_usdt_out_001/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/total cost basis usd for task_sol_basis_001/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark as internal transfer/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /classify as personal withdrawal/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /import missing source data/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /enter manual cost basis/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark basis unknown/i })).toBeInTheDocument()

    expect(screen.queryByText(/investment review/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^hold$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^add$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^trim$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^exit$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^research$/i })).not.toBeInTheDocument()
  })

  it('submits an internal transfer decision using the durable accounting request shape', async () => {
    const user = userEvent.setup()
    render(<AccountingReviewPage />)

    await screen.findByText('task_binance_usdt_out_001')
    await user.type(
      screen.getByLabelText(/rationale for task_binance_usdt_out_001/i),
      'Confirmed destination deposit in Hyperliquid.'
    )
    await user.type(screen.getByLabelText(/destination source for task_binance_usdt_out_001/i), 'hyperliquid')
    await user.type(screen.getByLabelText(/destination evidence key for task_binance_usdt_out_001/i), 'hl-deposit-498-usdt')
    await user.type(screen.getByLabelText(/destination quantity for task_binance_usdt_out_001/i), '498')
    await user.type(screen.getByLabelText(/fee quantity for task_binance_usdt_out_001/i), '2')
    await user.type(screen.getByLabelText(/fee asset for task_binance_usdt_out_001/i), 'USDT')
    await user.click(screen.getByRole('button', { name: /mark as internal transfer/i }))

    await waitFor(() => expect(accountingReviewAPI.decide).toHaveBeenCalledTimes(1))
    expect(accountingReviewAPI.decide).toHaveBeenCalledWith({
      task_id: 'task_binance_usdt_out_001',
      action: 'internal_transfer',
      idempotency_key: expect.stringContaining('task_binance_usdt_out_001-internal_transfer-'),
      rationale: 'Confirmed destination deposit in Hyperliquid.',
      internal_transfer: {
        to_source: 'hyperliquid',
        to_evidence_key: 'hl-deposit-498-usdt',
        to_quantity: '498',
        fee_quantity: '2',
        fee_asset_symbol: 'USDT',
      },
    })
    expect(await screen.findByText(/resolved as accounting_transfer_link/i)).toBeInTheDocument()
    expect(accountingReviewAPI.tasks).toHaveBeenCalledTimes(2)
  })

  it('submits a manual cost basis decision with entered basis fields', async () => {
    const user = userEvent.setup()
    jest.mocked(accountingReviewAPI.decide).mockResolvedValueOnce({
      task_id: 'task_sol_basis_001',
      task_status: 'resolved',
      decision_type: 'accounting_cost_basis_decision',
      decision_id: 43,
      replayed: false,
    })
    render(<AccountingReviewPage />)

    await screen.findByText('task_sol_basis_001')
    await user.type(screen.getByLabelText(/basis quantity for task_sol_basis_001/i), '25')
    await user.type(screen.getByLabelText(/total cost basis usd for task_sol_basis_001/i), '3250')
    await user.type(screen.getByLabelText(/basis method for task_sol_basis_001/i), 'manual_average')
    await user.click(screen.getByRole('button', { name: /enter manual cost basis/i }))

    await waitFor(() => expect(accountingReviewAPI.decide).toHaveBeenCalledTimes(1))
    expect(accountingReviewAPI.decide).toHaveBeenCalledWith({
      task_id: 'task_sol_basis_001',
      action: 'manual_cost_basis',
      idempotency_key: expect.stringContaining('task_sol_basis_001-manual_cost_basis-'),
      rationale: null,
      cost_basis: {
        quantity: '25',
        cost_basis_usd: '3250',
        basis_method: 'manual_average',
      },
    })
  })

  it('submits a personal withdrawal decision without transfer or cost basis extras', async () => {
    const user = userEvent.setup()
    jest.mocked(accountingReviewAPI.decide).mockResolvedValueOnce({
      task_id: 'task_binance_usdt_out_001',
      task_status: 'resolved',
      decision_type: 'accounting_external_cashflow_classification',
      decision_id: 44,
      replayed: false,
    })
    render(<AccountingReviewPage />)

    await screen.findByText('task_binance_usdt_out_001')
    await user.type(
      screen.getByLabelText(/rationale for task_binance_usdt_out_001/i),
      'Confirmed this left the portfolio.'
    )
    await user.click(screen.getByRole('button', { name: /classify as personal withdrawal/i }))

    await waitFor(() => expect(accountingReviewAPI.decide).toHaveBeenCalledTimes(1))
    expect(accountingReviewAPI.decide).toHaveBeenCalledWith({
      task_id: 'task_binance_usdt_out_001',
      action: 'personal_withdrawal',
      idempotency_key: expect.stringContaining('task_binance_usdt_out_001-personal_withdrawal-'),
      rationale: 'Confirmed this left the portfolio.',
    })
  })

  it('blocks internal transfer submission until required details are entered', async () => {
    const user = userEvent.setup()
    render(<AccountingReviewPage />)

    await screen.findByText('task_binance_usdt_out_001')
    await user.click(screen.getByRole('button', { name: /mark as internal transfer/i }))

    expect(await screen.findByText(/enter destination source/i)).toBeInTheDocument()
    expect(accountingReviewAPI.decide).not.toHaveBeenCalled()
  })

  it('blocks internal transfer submission when destination quantity is not positive', async () => {
    const user = userEvent.setup()
    render(<AccountingReviewPage />)

    await screen.findByText('task_binance_usdt_out_001')
    await user.type(screen.getByLabelText(/destination source for task_binance_usdt_out_001/i), 'hyperliquid')
    await user.type(screen.getByLabelText(/destination evidence key for task_binance_usdt_out_001/i), 'hl-deposit-498-usdt')
    await user.type(screen.getByLabelText(/destination quantity for task_binance_usdt_out_001/i), '-498')
    await user.click(screen.getByRole('button', { name: /mark as internal transfer/i }))

    expect(await screen.findByText(/enter destination source/i)).toBeInTheDocument()
    expect(accountingReviewAPI.decide).not.toHaveBeenCalled()
  })

  it('shows loading, empty, and fetch error states', async () => {
    const pending = deferred<typeof accountingQueue>()
    jest.mocked(accountingReviewAPI.tasks).mockReturnValueOnce(pending.promise)

    const { unmount } = render(<AccountingReviewPage />)
    expect(screen.getByText(/loading accounting tasks/i)).toBeInTheDocument()

    pending.resolve({ ...accountingQueue, tasks: [] })
    expect(await screen.findByText(/no accounting tasks are open/i)).toBeInTheDocument()

    jest.mocked(accountingReviewAPI.tasks).mockRejectedValueOnce(new Error('accounting queue unavailable'))
    unmount()
    render(<AccountingReviewPage />)

    expect(await screen.findByText('accounting queue unavailable')).toBeInTheDocument()
  })

  it('keeps a task visible and reports submit failures', async () => {
    const user = userEvent.setup()
    jest.mocked(accountingReviewAPI.decide).mockRejectedValueOnce(new Error('task already resolved'))
    render(<AccountingReviewPage />)

    const task = await screen.findByTestId('accounting-task-task_binance_usdt_out_001')
    await user.click(within(task).getByRole('button', { name: /classify as personal withdrawal/i }))

    expect(await screen.findByText('task already resolved')).toBeInTheDocument()
    expect(screen.getByTestId('accounting-task-task_binance_usdt_out_001')).toBeInTheDocument()
  })
})
