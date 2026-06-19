import { render, screen, waitFor } from '@testing-library/react'
import TransactionsPage from '@/app/transactions/page'
import { portfolioAPI } from '@/lib/api'
import { dashboardTransactions } from './dashboard.fixtures'

const push = jest.fn()

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/transactions',
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
    transactions: jest.fn(),
  },
}))

describe('TransactionsPage mobile layout', () => {
  beforeEach(() => {
    push.mockReset()
    jest.mocked(portfolioAPI.transactions).mockReset()
    jest.mocked(portfolioAPI.transactions).mockResolvedValue(dashboardTransactions)
  })

  it('renders mobile transaction cards alongside a desktop-only table', async () => {
    const { container } = render(<TransactionsPage />)

    await waitFor(() => expect(screen.getByText(/3 records loaded/i)).toBeInTheDocument())

    expect(container.querySelectorAll('.mobile-transaction-card')).toHaveLength(dashboardTransactions.length)
    expect(container.querySelector('[data-testid="transaction-desktop-table"]')).toHaveClass('hidden', 'md:block')
    expect(container.querySelector('[data-testid="transaction-mobile-list"]')).toHaveClass('md:hidden')
  })
})
