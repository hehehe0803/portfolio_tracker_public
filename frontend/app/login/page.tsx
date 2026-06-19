'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/providers/auth-provider'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [step, setStep] = useState<'credentials' | 'totp'>('credentials')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login, isAuthenticated, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.push('/')
    }
  }, [isAuthenticated, isLoading, router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const result = await login(username, password, step === 'totp' ? totpCode : undefined)
      if (result.totp_required) {
        setStep('totp')
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  if (isLoading) {
    return (
      <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-8">
        <section className="panel hero-shell w-full max-w-md p-7 text-center sm:p-9">
          <span className="badge-green mx-auto"><span className="signal-dot" />session</span>
          <h1 className="mt-5 text-2xl font-semibold tracking-[-0.04em] text-bright">Restoring session</h1>
          <p className="panel-subtitle mt-3">
            Validating your saved local access token before opening the dashboard.
          </p>
          <div className="surface-row mt-6 px-4 py-3 font-mono text-sm text-dim">
            Checking /me<span className="cursor" />
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-8">
      <div className="mx-auto grid w-full max-w-6xl gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="hero-shell panel terminal-grid hidden p-8 lg:block">
          <p className="panel-header">Portfolio tracker / stitch terminal redesign</p>
          <h1 className="mt-4 text-5xl font-semibold tracking-[-0.06em] text-bright">
            Aegis Terminal access console
          </h1>
          <p className="panel-subtitle mt-5 max-w-2xl">
            Inspired by the Stitch “Aegis Terminal” direction: dark fintech surfaces, semantic green / amber / cyan accents, higher information density, and a calmer command-center hierarchy.
          </p>

          <div className="mt-8 grid gap-4 md:grid-cols-2">
            <div className="surface-row p-4">
              <p className="metric-label">Security posture</p>
              <div className="mt-3 flex items-center gap-2 text-sm text-green">
                <span className="signal-dot" />
                Authenticated local node
              </div>
            </div>
            <div className="surface-row p-4">
              <p className="metric-label">Source coverage</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <span className="badge-green">Binance</span>
                <span className="badge-blue">XTB</span>
              </div>
            </div>
          </div>

          <div className="mt-6 grid gap-3">
            <TelemetryLine label="Mode" value="Personal treasury monitor" tone="green" />
            <TelemetryLine label="UI system" value="Aegis Terminal" tone="cyan" />
            <TelemetryLine label="Access path" value={step === 'credentials' ? 'Credential gate' : 'TOTP verification'} tone="amber" />
          </div>
        </section>

        <section className="panel hero-shell p-7 sm:p-9">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="panel-header">Operator authentication</p>
              <h2 className="panel-title mt-2">Mission control</h2>
            </div>
            <span className="badge-green"><span className="signal-dot" />secure</span>
          </div>

          <p className="panel-subtitle mt-4">
            {step === 'credentials'
              ? 'Enter the local dashboard credentials to unlock portfolio telemetry, imports, and sync controls.'
              : 'Enter the authenticator code to complete the secure handshake.'}
          </p>

          <div className="mt-6 surface-row px-4 py-3">
            <p className="metric-label">Current phase</p>
            <p className="mt-2 font-mono text-sm text-bright">
              {step === 'credentials' ? 'Step 1/2 · Credentials' : 'Step 2/2 · Verify identity'}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4" suppressHydrationWarning>
            {step === 'credentials' ? (
              <>
                <div>
                  <label htmlFor="username" className="uppercase-label block mb-2">Username</label>
                  <input
                    id="username"
                    type="text"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    className="t-input"
                    placeholder="admin"
                    required
                    autoComplete="username"
                  />
                </div>
                <div>
                  <label htmlFor="password" className="uppercase-label block mb-2">Password</label>
                  <input
                    id="password"
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    className="t-input"
                    placeholder="••••••••"
                    required
                    autoComplete="current-password"
                  />
                </div>
              </>
            ) : (
              <div>
                <label htmlFor="totp-code" className="uppercase-label block mb-2">Authenticator code</label>
                <input
                  id="totp-code"
                  type="text"
                  inputMode="numeric"
                  value={totpCode}
                  onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  className="t-input text-center text-2xl tracking-[0.5em]"
                  placeholder="000000"
                  required
                  autoFocus
                />
              </div>
            )}

            {error ? (
              <div className="rounded-2xl border border-[rgba(255,107,107,0.22)] bg-[rgba(255,107,107,0.08)] px-4 py-3 text-sm text-danger">
                {error}
              </div>
            ) : null}

            <div className="flex flex-col gap-3 pt-2 sm:flex-row">
              <button type="submit" className="btn-primary flex-1" disabled={loading}>
                {loading
                  ? 'Processing'
                  : step === 'totp'
                    ? 'Verify code'
                    : 'Authenticate'}
              </button>

              {step === 'totp' ? (
                <button
                  type="button"
                  className="btn-ghost flex-1"
                  onClick={() => { setStep('credentials'); setTotpCode(''); setError('') }}
                >
                  Back
                </button>
              ) : null}
            </div>
          </form>

          <div className="mt-8 surface-row flex items-center gap-3 px-4 py-3 font-mono text-sm text-dim">
            <span className="signal-dot" />
            Secure channel established<span className="cursor" />
          </div>
        </section>
      </div>
    </div>
  )
}

function TelemetryLine({ label, value, tone }: { label: string; value: string; tone: 'green' | 'amber' | 'cyan' }) {
  return (
    <div className="surface-row flex items-center justify-between gap-4 px-4 py-3">
      <div>
        <p className="metric-label">{label}</p>
      </div>
      <p className={`font-mono text-sm ${tone === 'amber' ? 'text-amber' : tone === 'cyan' ? 'text-[var(--cyan)]' : 'text-green'}`}>
        {value}
      </p>
    </div>
  )
}
