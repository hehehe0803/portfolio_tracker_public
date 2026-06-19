'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { useAuth } from '@/components/providers/auth-provider'
import { importsAPI, type ImportArtifact } from '@/lib/api'

export default function ImportPage() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const fileRef = useRef<HTMLInputElement>(null)

  const [imports, setImports] = useState<ImportArtifact[]>([])
  const [uploading, setUploading] = useState(false)
  const [confirming, setConfirming] = useState<number | null>(null)
  const [pending, setPending] = useState<ImportArtifact | null>(null)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) { router.push("/login"); return }
    loadImports()
  }, [isAuthenticated, isLoading, router])

  if (isLoading || !isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg)', fontFamily: 'monospace' }}>
        <span className="text-green text-sm">[ AUTH CHECK<span className="cursor">_</span> ]</span>
      </div>
    )
  }

  async function loadImports() {
    try {
      setImports(await importsAPI.list())
    } catch {}
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    setSuccessMsg('')
    setUploading(true)
    try {
      const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
      const isBinanceExport = extension === 'zip' || extension === 'csv'
      const result = isBinanceExport
        ? await importsAPI.uploadBinance(file)
        : await importsAPI.uploadXtb(file)
      if (result.error) {
        setError(result.error)
      } else {
        setPending(await importsAPI.get(result.artifact_id))
        loadImports()
      }
    } catch (err: any) {
      setError(err.message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function handleConfirm(id: number) {
    setConfirming(id)
    setError('')
    setSuccessMsg('')
    try {
      const result = await importsAPI.confirm(id)
      setPending(null)
      loadImports()
      setSuccessMsg(`Committed ${result.committed} transactions (${result.duplicates_skipped} duplicates skipped)`)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setConfirming(null)
    }
  }

  function statusBadge(status: string) {
    if (status === 'committed') return <span className="badge-green">{status.toUpperCase()}</span>
    if (status === 'reviewed' || status === 'pending') return <span className="badge-amber">{status.toUpperCase()}</span>
    if (status === 'failed') return <span className="badge-red">{status.toUpperCase()}</span>
    return <span className="badge-amber">{status.toUpperCase()}</span>
  }

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <Sidebar />

      <main className="px-4 pb-8 pt-[60px] md:ml-[220px] md:px-6 lg:px-8">
        <div className="mx-auto max-w-4xl space-y-6 py-8">

          {/* Page header */}
          <div>
            <p className="text-bright text-xs tracking-widest uppercase">[ DATA INGEST / BROKER IMPORTS ]</p>
            <p className="text-dim text-xs mt-1">{'// Upload XTB statements or Binance export archives (.zip/.csv)'}</p>
          </div>

          {/* Upload zone */}
          <div className="panel p-6">
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.html,.mhtml,.mht,.zip,.csv"
              onChange={handleFileChange}
              className="hidden"
              id="file-upload"
            />
            <label
              htmlFor="file-upload"
              className={`flex flex-col items-center justify-center rounded border border-dashed p-12 transition-all hover:shadow-[0_0_8px_rgba(155,245,106,0.15)] ${uploading ? 'pointer-events-none cursor-wait opacity-50' : 'cursor-pointer'}`}
              style={{ borderColor: 'var(--border-strong)' }}
            >
              {uploading ? (
                <p className="text-green text-xs tracking-widest uppercase cursor-wait">[ PARSING FILE... ]</p>
              ) : (
                <>
                  <p className="text-green text-xs tracking-widest uppercase">[ DROP BROKER EXPORT HERE ]</p>
                  <p className="text-dim text-xs mt-2">{'// xtb: .xlsx/.html/.mhtml/.mht · binance: original .zip/.csv'}</p>
                </>
              )}
            </label>

            {error && (
              <div className="mt-3 text-xs val-neg">[ ERR: {error} ]</div>
            )}
            {successMsg && (
              <div className="mt-3 text-xs val-pos">[ OK: {successMsg} ]</div>
            )}
          </div>

          {/* Parse preview panel */}
          {pending && pending.status === 'reviewed' && pending.preview && (
            <div className="panel p-6 mt-4" style={{ borderLeft: '2px solid var(--primary)' }}>
              <p className="text-bright text-xs tracking-widest uppercase mb-4">
                [ PARSE RESULT: {pending.filename} ]
              </p>

              {/* Stats row */}
              <div className="flex gap-6 mb-4">
                <div>
                  <p className="uppercase-label">PARSED</p>
                  <p className="text-bright text-2xl font-bold">{pending.preview.total_parsed}</p>
                </div>
                <div>
                  <p className="uppercase-label">NEW</p>
                  <p className="val-pos text-2xl font-bold">{pending.preview.new}</p>
                </div>
                <div>
                  <p className="uppercase-label">DUPLICATES</p>
                  <p className="text-dim text-2xl font-bold">{pending.preview.duplicates}</p>
                </div>
              </div>

              {/* Sample table */}
              {pending.preview.sample.length > 0 && (
                <div className="mb-4 overflow-x-auto">
                  <p className="text-dim text-xs mb-2">{'// sample — first 10 new records'}</p>
                  <table className="t-table w-full text-xs">
                    <thead>
                      <tr>
                        <th className="text-left">Date</th>
                        <th className="text-left">Type</th>
                        <th className="text-left">Symbol</th>
                        <th className="text-right">Amount</th>
                        <th className="text-left">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pending.preview.sample.map((row, i) => (
                        <tr key={i}>
                          <td>{row.date.slice(0, 10)}</td>
                          <td className="uppercase">{row.type.toLowerCase()}</td>
                          <td className="font-mono">{row.symbol || '—'}</td>
                          <td className="text-right">{row.amount != null ? row.amount.toFixed(2) : '—'}</td>
                          <td className="text-dim truncate max-w-[120px]">{row.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Action buttons */}
              <div className="flex gap-3 mt-2">
                <button
                  onClick={() => handleConfirm(pending.id)}
                  disabled={confirming === pending.id}
                  className="btn-primary disabled:opacity-50"
                >
                  {confirming === pending.id ? '[ COMMITTING... ]' : `[ COMMIT ${pending.preview.new} RECORDS ]`}
                </button>
                <button
                  onClick={() => setPending(null)}
                  className="btn-ghost"
                >
                  [ DISCARD ]
                </button>
              </div>
            </div>
          )}

          {/* Import history */}
          <div className="panel p-6 mt-4">
            <div className="panel-header">[ IMPORT HISTORY ]</div>
            {imports.length === 0 ? (
              <p className="text-dim text-xs">{'// no imports on record'}</p>
            ) : (
              <div className="space-y-2 mt-3">
                {imports.map(imp => (
                  <div key={imp.id} className="flex items-center justify-between py-2 border-b" style={{ borderColor: 'var(--border)' }}>
                    <div>
                      <p className="text-bright text-xs">{imp.filename}</p>
                      <p className="text-dim text-xs mt-0.5">
                        {new Date(imp.created_at).toLocaleString()} &middot; {imp.parsed_count} parsed, {imp.committed_count} committed
                      </p>
                    </div>
                    <div className="text-right flex flex-col items-end gap-1">
                      {statusBadge(imp.status)}
                      {imp.status === 'reviewed' && (
                        <button
                          onClick={async () => {
                            const full = await importsAPI.get(imp.id)
                            setPending(full)
                          }}
                          className="text-green text-xs hover:underline"
                        >
                          Review →
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>
      </main>
    </div>
  )
}
