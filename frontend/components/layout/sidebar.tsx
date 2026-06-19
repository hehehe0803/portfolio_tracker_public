'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const navigation = [
  { name: 'Overview',     href: '/',             icon: '▣', hint: 'Dashboard' },
  { name: 'Portfolio',    href: '/portfolio',     icon: '◈', hint: 'Details & review' },
  { name: 'Watchlist',    href: '/watchlist',     icon: '◇', hint: 'Idea pipeline' },
  { name: 'Transactions', href: '/transactions',  icon: '≡', hint: 'Ledger' },
  { name: 'Import',       href: '/import',        icon: '↑', hint: 'Broker sync' },
  { name: 'Settings',     href: '/settings',      icon: '⚙', hint: 'Config & keys' },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside
      className="fixed left-0 hidden md:flex flex-col"
      style={{
        top: 52,
        width: 220,
        height: 'calc(100vh - 52px)',
        background: 'var(--bg-0)',
        borderRight: '1px solid var(--line-1)',
        padding: '16px 0',
      }}
    >
      {/* nav links */}
      <nav style={{ flex: 1, paddingTop: 4 }}>
        {navigation.map(item => {
          const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href))
          return (
            <Link
              key={item.href}
              href={item.href}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '9px 20px',
                position: 'relative',
                textDecoration: 'none',
                transition: 'background 0.1s',
              }}
              className={active ? '' : 'hover:bg-[var(--bg-2)]'}
            >
              {/* active indicator bar */}
              {active && (
                <span
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 8,
                    bottom: 8,
                    width: 2,
                    background: 'var(--fg-0)',
                  }}
                />
              )}

              <span
                style={{
                  fontFamily: 'var(--font-geist-mono)',
                  fontSize: 13,
                  color: active ? 'var(--fg-0)' : 'var(--fg-3)',
                  width: 16,
                  flexShrink: 0,
                  textAlign: 'center',
                }}
              >
                {item.icon}
              </span>

              <div>
                <div
                  style={{
                    fontSize: 12.5,
                    fontWeight: 500,
                    color: active ? 'var(--fg-0)' : 'var(--fg-2)',
                    letterSpacing: '-0.01em',
                  }}
                >
                  {item.name}
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: 'var(--fg-4)',
                    fontFamily: 'var(--font-geist-mono)',
                    letterSpacing: '0.06em',
                  }}
                >
                  {item.hint}
                </div>
              </div>
            </Link>
          )
        })}
      </nav>

      {/* footer label */}
      <div style={{ padding: '0 20px 8px' }}>
        <span
          style={{
            fontFamily: 'var(--font-geist-mono)',
            fontSize: 9,
            color: 'var(--fg-4)',
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
          }}
        >
          Portfolio Tracker
        </span>
      </div>
    </aside>
  )
}
