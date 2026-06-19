import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from '@/components/providers/auth-provider'
import { authAPI } from '@/lib/api'

const push = jest.fn()

jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push,
  }),
}))

jest.mock('@/lib/api', () => ({
  authAPI: {
    login: jest.fn(),
    me: jest.fn(),
  },
}))

function Consumer() {
  const { isAuthenticated, isLoading, user, login, logout } = useAuth()

  return (
    <div>
      <div data-testid="auth-state">{isAuthenticated ? 'yes' : 'no'}</div>
      <div data-testid="loading-state">{isLoading ? 'loading' : 'ready'}</div>
      <div data-testid="user-name">{user?.username ?? 'none'}</div>
      <button onClick={() => { void login('admin', 'secret').catch(() => undefined) }}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    push.mockReset()
    localStorage.clear()
    jest.mocked(authAPI.login).mockReset()
    jest.mocked(authAPI.me).mockReset()
  })

  it('restores a persisted session from storage', async () => {
    localStorage.setItem('access_token', 'access-token')
    jest.mocked(authAPI.me).mockResolvedValue({
      id: 1,
      username: 'admin',
      totp_enabled: false,
      telegram_configured: false,
    })

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )

    expect(screen.getByTestId('loading-state')).toHaveTextContent('loading')

    await waitFor(() => {
      expect(screen.getByTestId('loading-state')).toHaveTextContent('ready')
    })

    expect(screen.getByTestId('auth-state')).toHaveTextContent('yes')
    expect(screen.getByTestId('user-name')).toHaveTextContent('admin')
    expect(authAPI.me).toHaveBeenCalledTimes(1)
  })

  it('clears invalid persisted tokens when session bootstrap fails', async () => {
    localStorage.setItem('access_token', 'stale-token')
    localStorage.setItem('refresh_token', 'stale-refresh')
    jest.mocked(authAPI.me).mockRejectedValue(new Error('expired'))

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading-state')).toHaveTextContent('ready')
    })

    expect(screen.getByTestId('auth-state')).toHaveTextContent('no')
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
  })

  it('stores tokens and navigates after a successful login', async () => {
    const user = userEvent.setup()
    jest.mocked(authAPI.login).mockResolvedValue({
      access_token: 'new-access',
      refresh_token: 'new-refresh',
      token_type: 'bearer',
      totp_required: false,
    })
    jest.mocked(authAPI.me).mockResolvedValue({
      id: 1,
      username: 'admin',
      totp_enabled: true,
      telegram_configured: true,
    })

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading-state')).toHaveTextContent('ready')
    })

    await user.click(screen.getByRole('button', { name: 'login' }))

    await waitFor(() => {
      expect(screen.getByTestId('auth-state')).toHaveTextContent('yes')
    })

    expect(localStorage.getItem('access_token')).toBe('new-access')
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh')
    expect(push).toHaveBeenCalledWith('/')
  })

  it('clears tokens and auth state if login validation via me fails', async () => {
    const user = userEvent.setup()
    jest.mocked(authAPI.login).mockResolvedValue({
      access_token: 'bad-access',
      refresh_token: 'bad-refresh',
      token_type: 'bearer',
      totp_required: false,
    })
    jest.mocked(authAPI.me).mockRejectedValue(new Error('profile lookup failed'))

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading-state')).toHaveTextContent('ready')
    })

    await user.click(screen.getByRole('button', { name: 'login' }))

    expect(screen.getByTestId('auth-state')).toHaveTextContent('no')
    expect(screen.getByTestId('user-name')).toHaveTextContent('none')
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
    expect(push).not.toHaveBeenCalled()
  })

  it('does not persist tokens or navigate while totp is still required', async () => {
    const user = userEvent.setup()
    jest.mocked(authAPI.login).mockResolvedValue({
      access_token: '',
      refresh_token: '',
      token_type: 'bearer',
      totp_required: true,
    })

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading-state')).toHaveTextContent('ready')
    })

    await user.click(screen.getByRole('button', { name: 'login' }))

    await waitFor(() => {
      expect(authAPI.login).toHaveBeenCalledTimes(1)
    })

    expect(screen.getByTestId('auth-state')).toHaveTextContent('no')
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(push).not.toHaveBeenCalled()
  })

  it('clears session state and routes to login on logout', async () => {
    localStorage.setItem('access_token', 'token')
    localStorage.setItem('refresh_token', 'refresh')
    jest.mocked(authAPI.me).mockResolvedValue({
      id: 1,
      username: 'admin',
      totp_enabled: false,
      telegram_configured: false,
    })

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('auth-state')).toHaveTextContent('yes')
    })

    await act(async () => {
      screen.getByRole('button', { name: 'logout' }).click()
    })

    expect(screen.getByTestId('auth-state')).toHaveTextContent('no')
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
    expect(push).toHaveBeenCalledWith('/login')
  })
})
