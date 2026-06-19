'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/components/providers/auth-provider'
import { useEffect, useState } from 'react'

const PAGE_LABELS: Record<string, string> = {
  '/':             'Overview',
  '/portfolio':    'Portfolio',
  '/holdings':     'Holdings',
  '/transactions': 'Transactions',
  '/import':       'Import',
  '/settings':     'Settings',
}

const mobileNavigation = [
  { name: 'Overview',     href: '/' },
  { name: 'Portfolio',    href: '/portfolio' },
  { name: 'Transactions', href: '/transactions' },
  { name: 'Import',       href: '/import' },
  { name: 'Settings',     href: '/settings' },
]

export function Header() {
  const { user, logout, isAuthenticated } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [timeStr, setTimeStr] = useState('')
  const pathname = usePathname()

  useEffect(() => {
    const update = () => {
      const now = new Date()
      const d = now.toISOString().slice(0, 10).replace(/-/g, ' · ').replace(' · ', ' ')
      const t = now.toISOString().slice(11, 19)
      setTimeStr(`${d} · ${t} UTC`)
    }
    update()
    const id = window.setInterval(update, 1000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    if (!isAuthenticated) setMobileOpen(false)
  }, [isAuthenticated])

  // derive page label from pathname
  const pageLabel =
    PAGE_LABELS[pathname] ??
    (pathname.startsWith('/holdings/') ? 'Asset Detail' : 'Portfolio Tracker')

  return (
    <header
      className="fixed left-0 right-0 top-0 z-50"
      style={{ height: 60, borderBottom: '1px solid var(--line-1)', background: 'rgba(10,10,11,0.96)', backdropFilter: 'blur(14px)' }}
    >
      <div
        className="mx-auto flex h-full items-center gap-4 px-4 sm:gap-6 sm:px-6 lg:px-8"
        style={{ maxWidth: 1600 }}
      >
        {/* breadcrumb */}
        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
          <span className="panel-header shrink-0">{pageLabel.toUpperCase()}</span>
          <span aria-hidden="true" style={{ width: 1, height: 18, background: 'var(--line-2)' }} />
          <span
            className="truncate"
            style={{
              fontSize: 14,
              fontWeight: 500,
              color: 'var(--fg-0)',
              letterSpacing: '-0.01em',
              whiteSpace: 'nowrap',
              maxWidth: '44vw',
            }}
          >
            Portfolio Tracker
          </span>
        </div>

        <div style={{ flex: 1 }} />

        {/* timestamp */}
        <span
          className="hidden lg:block"
          style={{
            fontFamily: 'var(--font-geist-mono)',
            fontSize: 11,
            color: 'var(--fg-2)',
            letterSpacing: '0.01em',
          }}
        >
          {timeStr || '---- -- -- --:--:-- UTC'}
        </span>

        {/* divider */}
        <span
          className="hidden lg:block"
          style={{ width: 1, height: 16, background: 'var(--line-2)' }}
        />

        {/* user + auth */}
        {isAuthenticated && user ? (
          <span className="hidden md:block" style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10.5, color: 'var(--fg-2)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
            {user.username}
          </span>
        ) : null}

        <div className="flex items-center gap-2">
          {isAuthenticated ? (
            <>
              <Link href="/settings" className="btn-ghost hidden sm:inline-flex">
                Settings
              </Link>
              <button onClick={logout} className="btn-ghost hidden sm:inline-flex">
                Logout
              </button>
            </>
          ) : (
            <Link href="/login" className="btn-primary">
              Login
            </Link>
          )}

          {isAuthenticated ? (
            <button
              type="button"
              className="btn-ghost md:hidden"
              aria-label={mobileOpen ? 'Close navigation menu' : 'Open navigation menu'}
              aria-expanded={mobileOpen}
              aria-controls="mobile-navigation"
              onClick={() => setMobileOpen(o => !o)}
            >
              {mobileOpen ? '✕' : '≡'}
            </button>
          ) : null}
        </div>
      </div>

      {/* mobile nav drawer */}
      {isAuthenticated && mobileOpen ? (
        <div
          id="mobile-navigation"
          style={{ borderTop: '1px solid var(--line-1)', background: 'var(--bg-0)', padding: '12px 16px' }}
          className="md:hidden"
        >
          <nav className="flex flex-col gap-1">
            {mobileNavigation.map(item => (
              <Link
                key={item.href}
                href={item.href}
                style={{
                  display: 'block',
                  padding: '10px 14px',
                  fontSize: 13,
                  fontWeight: 500,
                  color: pathname === item.href ? 'var(--fg-0)' : 'var(--fg-2)',
                  borderLeft: pathname === item.href ? '2px solid var(--fg-0)' : '2px solid transparent',
                  letterSpacing: '-0.01em',
                }}
                onClick={() => setMobileOpen(false)}
              >
                {item.name}
              </Link>
            ))}
            <button
              type="button"
              onClick={() => { setMobileOpen(false); logout() }}
              className="btn-ghost mt-2 w-full justify-center"
            >
              Logout
            </button>
          </nav>
        </div>
      ) : null}
    </header>
  )
}
