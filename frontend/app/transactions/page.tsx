'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { useAuth } from '@/components/providers/auth-provider'
import { portfolioAPI, type Transaction } from '@/lib/api'

function fmtUsd(n: number | null | undefined, decimals = 2) {
  if (n == null) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)
}

function fmtQty(n: number) {
  return n.toLocaleString('en-US', { maximumFractionDigits: 8 })
}

function fmtTxType(type: string) {
  return type.replace(/_/g, ' ')
}

export default function TransactionsPage() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [txs, setTxs] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [institution, setInstitution] = useState('')
  const [asset, setAsset] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await portfolioAPI.transactions({ institution: institution || undefined, asset: asset || undefined, limit: 200 })
      setTxs(data)
    } catch {}
    finally { setLoading(false) }
  }, [asset, institution])

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) { router.push("/login"); return }
    load()
  }, [isAuthenticated, isLoading, load, router])

  if (isLoading || !isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg)', fontFamily: 'monospace' }}>
        <span className="text-green text-sm">[ AUTH CHECK<span className="cursor">_</span> ]</span>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <Sidebar />

      <main className="px-4 pb-8 pt-[60px] md:ml-[220px] md:px-6 lg:px-8">
        <div className="mx-auto max-w-5xl space-y-4 py-8">

          <div>
            <h1 className="text-bright text-sm tracking-widest uppercase">[ TRANSACTION LOG ]</h1>
            <p className="text-dim text-xs mt-1">{`// ${txs.length} records loaded`}</p>
          </div>

          <div className="flex flex-wrap gap-4 items-end">
            <div className="flex flex-col gap-1">
              <label className="uppercase-label text-dim">Institution</label>
              <select
                value={institution}
                onChange={e => setInstitution(e.target.value)}
                className="t-select"
              >
                <option value="">ALL</option>
                <option value="binance">Binance</option>
                <option value="xtb">XTB</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="uppercase-label text-dim">Asset</label>
              <input
                placeholder="e.g. BTC"
                value={asset}
                onChange={e => setAsset(e.target.value)}
                className="t-input"
              />
            </div>
          </div>

          <div className="panel">
            {loading ? (
              <div className="p-8 text-center uppercase-label text-dim cursor">LOADING RECORDS</div>
            ) : txs.length === 0 ? (
              <div className="p-8 text-center text-dim text-xs">[ NO RECORDS FOUND ]</div>
            ) : (
              <>
                <div data-testid="transaction-mobile-list" className="space-y-2 p-3 md:hidden">
                  {txs.map(tx => (
                    <article key={tx.id} className="mobile-transaction-card surface-row p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-sm font-semibold text-bright">{tx.asset}</span>
                            <span className={tx.institution === 'binance' ? 'badge-green' : tx.institution === 'xtb' ? 'badge-amber' : 'badge-dim'}>
                              {fmtTxType(tx.type)}
                            </span>
                          </div>
                          <div className="mt-2 text-xs text-dim">
                            {new Date(tx.timestamp).toLocaleDateString()} · {tx.institution.toUpperCase()}
                          </div>
                        </div>
                        <div className="text-right font-mono tabular-nums">
                          <div className="text-sm text-bright">{fmtUsd(tx.total_usd)}</div>
                          <div className="mt-1 text-[11px] text-dim">{fmtQty(tx.quantity)}</div>
                        </div>
                      </div>
                      <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-[var(--line-1)] pt-3 text-xs">
                        <div>
                          <dt className="uppercase-label">Price</dt>
                          <dd className="mt-1 font-mono text-bright">{fmtUsd(tx.price_usd, 4)}</dd>
                        </div>
                        <div className="text-right">
                          <dt className="uppercase-label">Fee</dt>
                          <dd className="mt-1 font-mono text-bright">{tx.fee ? `${tx.fee} ${tx.fee_currency}` : '—'}</dd>
                        </div>
                      </dl>
                    </article>
                  ))}
                </div>
                <div data-testid="transaction-desktop-table" className="hidden overflow-x-auto md:block">
                  <table className="t-table">
                    <thead>
                      <tr>
                        <th className="text-left">DATE</th>
                        <th className="text-left">INSTITUTION</th>
                        <th className="text-left">TYPE</th>
                        <th className="text-left">ASSET</th>
                        <th className="text-right">QTY</th>
                        <th className="text-right">PRICE</th>
                        <th className="text-right">TOTAL</th>
                      </tr>
                    </thead>
                    <tbody>
                      {txs.map(tx => (
                        <tr key={tx.id}>
                          <td className="text-dim">{new Date(tx.timestamp).toLocaleDateString()}</td>
                          <td>
                            <span className={tx.institution === 'binance' ? 'badge-green' : tx.institution === 'xtb' ? 'badge-amber' : ''}>
                              {tx.institution.toUpperCase()}
                            </span>
                          </td>
                          <td className="text-dim">{fmtTxType(tx.type)}</td>
                          <td className="text-bright font-bold">{tx.asset}</td>
                          <td className="text-right font-mono">{fmtQty(tx.quantity)}</td>
                          <td className="text-right font-mono">{fmtUsd(tx.price_usd, 4)}</td>
                          <td className="text-right font-mono">{fmtUsd(tx.total_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

        </div>
      </main>
    </div>
  )
}
