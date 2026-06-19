import { render, screen } from '@testing-library/react'
import LoginPage from '@/app/login/page'

const push = jest.fn()
const authState = {
  isAuthenticated: false,
  isLoading: false,
  login: jest.fn(),
}

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}))

jest.mock('@/components/providers/auth-provider', () => ({
  useAuth: () => authState,
}))

describe('LoginPage session restore UX', () => {
  beforeEach(() => {
    push.mockReset()
    authState.isAuthenticated = false
    authState.isLoading = false
    authState.login.mockReset()
  })

  it('shows a restoring-session panel instead of the credential form while auth is validating', () => {
    authState.isLoading = true

    render(<LoginPage />)

    expect(screen.getByText(/restoring session/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/username/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^authenticate$/i })).not.toBeInTheDocument()
  })
})
