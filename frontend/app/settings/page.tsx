'use client'

import Image from 'next/image'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Header } from '@/components/layout/header'
import { Sidebar } from '@/components/layout/sidebar'
import { useAuth } from '@/components/providers/auth-provider'
import { authAPI, settingsAPI, alertsAPI } from '@/lib/api'

export default function SettingsPage() {
  const { isAuthenticated, isLoading, user } = useAuth()
  const router = useRouter()

  // Binance keys
  const [binanceKey, setBinanceKey] = useState('')
  const [binanceSecret, setBinanceSecret] = useState('')
  const [binanceMsg, setBinanceMsg] = useState('')

  // Telegram
  const [telegramId, setTelegramId] = useState('')
  const [telegramMsg, setTelegramMsg] = useState('')

  // TOTP
  const [totpQr, setTotpQr] = useState('')
  const [totpSecret, setTotpSecret] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [totpMsg, setTotpMsg] = useState('')
  const [disableCode, setDisableCode] = useState('')

  // Password
  const [currPass, setCurrPass] = useState('')
  const [newPass, setNewPass] = useState('')
  const [passMsg, setPassMsg] = useState('')

  // Alerts
  const [rules, setRules] = useState<any[]>([])
  const [newAsset, setNewAsset] = useState('')
  const [newCond, setNewCond] = useState('price_drop_pct')
  const [newThresh, setNewThresh] = useState('')
  const [alertMsg, setAlertMsg] = useState('')

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) { router.push("/login"); return }
    loadRules()
  }, [isAuthenticated, isLoading, router])

  if (isLoading || !isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg)', fontFamily: 'monospace' }}>
        <span className="text-green text-sm">[ AUTH CHECK<span className="cursor">_</span> ]</span>
      </div>
    )
  }

  async function loadRules() {
    try { setRules(await alertsAPI.listRules()) } catch {}
  }

  async function saveBinance(e: React.FormEvent) {
    e.preventDefault()
    setBinanceMsg('')
    try {
      await settingsAPI.setBinanceKeys(binanceKey, binanceSecret)
      setBinanceMsg('Keys saved ✓')
      setBinanceKey(''); setBinanceSecret('')
    } catch (err: any) { setBinanceMsg(err.message) }
  }

  async function saveTelegram(e: React.FormEvent) {
    e.preventDefault()
    setTelegramMsg('')
    try {
      await settingsAPI.setTelegram(telegramId)
      setTelegramMsg('Chat ID saved ✓')
    } catch (err: any) { setTelegramMsg(err.message) }
  }

  async function setupTotp() {
    try {
      const r = await authAPI.totpSetup()
      setTotpQr(r.qr_code_base64)
      setTotpSecret(r.secret)
      setTotpMsg('')
    } catch (err: any) { setTotpMsg(err.message) }
  }

  async function verifyTotp(e: React.FormEvent) {
    e.preventDefault()
    try {
      const r = await authAPI.totpVerify(totpCode)
      setTotpMsg(r.message + ' — refresh the page to see updated status')
      setTotpQr(''); setTotpSecret(''); setTotpCode('')
    } catch (err: any) { setTotpMsg(err.message) }
  }

  async function disableTotp(e: React.FormEvent) {
    e.preventDefault()
    try {
      const r = await authAPI.totpDisable(disableCode)
      setTotpMsg(r.message)
      setDisableCode('')
    } catch (err: any) { setTotpMsg(err.message) }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault()
    setPassMsg('')
    try {
      const r = await authAPI.changePassword(currPass, newPass)
      setPassMsg(r.message)
      setCurrPass(''); setNewPass('')
    } catch (err: any) { setPassMsg(err.message) }
  }

  async function createAlert(e: React.FormEvent) {
    e.preventDefault()
    setAlertMsg('')
    try {
      await alertsAPI.createRule({ asset_symbol: newAsset.toUpperCase(), condition: newCond, threshold: parseFloat(newThresh) })
      setAlertMsg('Rule created ✓')
      setNewAsset(''); setNewThresh('')
      loadRules()
    } catch (err: any) { setAlertMsg(err.message) }
  }

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <Sidebar />

      <main className="px-4 pb-8 pt-[60px] md:ml-[220px] md:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl py-8">

          {/* Page header */}
          <div className="mb-6">
            <p className="text-bright text-xs tracking-widest uppercase">[ SYSTEM CONFIGURATION ]</p>
          </div>

          {/* Binance API Keys */}
          <div className="panel p-5 mb-4">
            <div className="panel-header">[ BINANCE API KEYS ]</div>
            <p className="text-dim text-xs mb-3">{'// Read-only keys only. Stored encrypted in database.'}</p>
            <form onSubmit={saveBinance} className="space-y-3">
              <div>
                <label className="uppercase-label text-dim block mb-1">API Key</label>
                <input
                  type="text"
                  placeholder="Enter API key"
                  value={binanceKey}
                  onChange={e => setBinanceKey(e.target.value)}
                  className="t-input w-full"
                />
              </div>
              <div>
                <label className="uppercase-label text-dim block mb-1">API Secret</label>
                <input
                  type="password"
                  placeholder="Enter API secret"
                  value={binanceSecret}
                  onChange={e => setBinanceSecret(e.target.value)}
                  className="t-input w-full"
                />
              </div>
              <button type="submit" className="btn-primary">[ SAVE KEYS ]</button>
              {binanceMsg && (
                binanceMsg.toLowerCase().includes('err') || binanceMsg.toLowerCase().includes('fail') || binanceMsg.toLowerCase().includes('invalid')
                  ? <p className="text-xs font-mono" style={{ color: 'var(--color-danger, #ff4141)' }}>[ ERR: {binanceMsg} ]</p>
                  : <p className="text-green text-xs font-mono">[ OK: {binanceMsg} ]</p>
              )}
            </form>
          </div>

          {/* Telegram Alerts */}
          <div className="panel p-5 mb-4">
            <div className="panel-header">[ TELEGRAM ALERTS ]</div>
            <div className="text-dim text-xs space-y-1 mb-3">
              <p>{'// 1. Start a chat with your bot.'}</p>
              <p>{'// 2. Send '}<span className="text-bright font-mono">/start</span>{' to get your chat ID.'}</p>
              <p>{'// 3. Paste the chat ID below.'}</p>
            </div>
            <form onSubmit={saveTelegram} className="flex gap-2">
              <input
                type="text"
                placeholder="Chat ID (e.g. 123456789)"
                value={telegramId}
                onChange={e => setTelegramId(e.target.value)}
                className="t-input flex-1"
              />
              <button type="submit" className="btn-primary">[ SAVE ]</button>
            </form>
            {telegramMsg && (
              telegramMsg.toLowerCase().includes('err') || telegramMsg.toLowerCase().includes('fail') || telegramMsg.toLowerCase().includes('invalid')
                ? <p className="text-xs font-mono mt-2" style={{ color: 'var(--color-danger, #ff4141)' }}>[ ERR: {telegramMsg} ]</p>
                : <p className="text-green text-xs font-mono mt-2">[ OK: {telegramMsg} ]</p>
            )}
          </div>

          {/* Two-Factor Auth */}
          <div className="panel p-5 mb-4">
            <div className="panel-header">[ TWO-FACTOR AUTH ]</div>
            {user?.totp_enabled ? (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <span className="badge-green">ENABLED</span>
                </div>
                <form onSubmit={disableTotp} className="flex gap-2">
                  <input
                    type="text"
                    inputMode="numeric"
                    placeholder="Enter code to disable"
                    value={disableCode}
                    onChange={e => setDisableCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    className="t-input flex-1"
                  />
                  <button type="submit" className="btn-danger">[ DISABLE ]</button>
                </form>
              </div>
            ) : (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="badge-red">DISABLED</span>
                </div>
                <p className="text-xs font-mono mb-3" style={{ color: '#ffb300' }}>{'// Required when accessing via tunnel'}</p>
                {!totpQr ? (
                  <button onClick={setupTotp} className="btn-primary">[ SETUP TOTP ]</button>
                ) : (
                  <div className="space-y-4">
                    <Image
                      src={`data:image/png;base64,${totpQr}`}
                      alt="TOTP QR code"
                      className="border border-panel rounded-sm w-48 h-48"
                      width={192}
                      height={192}
                    />
                    <p className="text-dim text-xs font-mono break-all">Secret: {totpSecret}</p>
                    <form onSubmit={verifyTotp} className="flex gap-2">
                      <input
                        type="text"
                        inputMode="numeric"
                        placeholder="6-digit code"
                        value={totpCode}
                        onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                        className="t-input flex-1"
                      />
                      <button type="submit" className="btn-primary">[ VERIFY ]</button>
                    </form>
                  </div>
                )}
              </div>
            )}
            {totpMsg && (
              totpMsg.toLowerCase().includes('err') || totpMsg.toLowerCase().includes('fail') || totpMsg.toLowerCase().includes('invalid')
                ? <p className="text-xs font-mono mt-2" style={{ color: 'var(--color-danger, #ff4141)' }}>[ ERR: {totpMsg} ]</p>
                : <p className="text-green text-xs font-mono mt-2">[ OK: {totpMsg} ]</p>
            )}
          </div>

          {/* Price Alerts */}
          <div className="panel p-5 mb-4">
            <div className="panel-header">[ PRICE ALERTS ]</div>
            <p className="text-dim text-xs mb-3">{'// Alerts fire every 10 minutes via Telegram.'}</p>
            <form onSubmit={createAlert} className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                <input
                  placeholder="Symbol (BTC)"
                  value={newAsset}
                  onChange={e => setNewAsset(e.target.value)}
                  className="t-input"
                  required
                />
                <select
                  value={newCond}
                  onChange={e => setNewCond(e.target.value)}
                  className="t-select"
                >
                  <option value="price_drop_pct">Price drops below</option>
                  <option value="price_rise_pct">Price rises above</option>
                </select>
                <input
                  type="number"
                  step="any"
                  placeholder="USD price"
                  value={newThresh}
                  onChange={e => setNewThresh(e.target.value)}
                  className="t-input"
                  required
                />
              </div>
              <button type="submit" className="btn-primary w-full">[ ADD RULE ]</button>
            </form>
            {alertMsg && (
              alertMsg.toLowerCase().includes('err') || alertMsg.toLowerCase().includes('fail') || alertMsg.toLowerCase().includes('invalid')
                ? <p className="text-xs font-mono mt-2" style={{ color: 'var(--color-danger, #ff4141)' }}>[ ERR: {alertMsg} ]</p>
                : <p className="text-green text-xs font-mono mt-2">[ OK: {alertMsg} ]</p>
            )}
            {rules.length > 0 && (
              <div className="space-y-1 mt-3">
                {rules.map(r => (
                  <div key={r.id} className="flex items-center justify-between py-1.5">
                    <span className={`text-xs font-mono ${r.is_active ? 'text-green' : 'text-dim'}`}>
                      {r.is_active ? '● ' : '○ '}
                      {r.asset_symbol} {r.condition === 'price_drop_pct' ? '↓' : '↑'} ${r.threshold}
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={async () => { await alertsAPI.toggleRule(r.id); loadRules() }}
                        className="btn-ghost text-xs"
                      >
                        {r.is_active ? '[ PAUSE ]' : '[ RESUME ]'}
                      </button>
                      <button
                        onClick={async () => { await alertsAPI.deleteRule(r.id); loadRules() }}
                        className="btn-danger text-xs"
                      >
                        [ DELETE ]
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Access Credentials */}
          <div className="panel p-5 mb-4">
            <div className="panel-header">[ ACCESS CREDENTIALS ]</div>
            <form onSubmit={changePassword} className="space-y-3">
              <div>
                <label className="uppercase-label text-dim block mb-1">Current Password</label>
                <input
                  type="password"
                  placeholder="Current password"
                  value={currPass}
                  onChange={e => setCurrPass(e.target.value)}
                  className="t-input w-full"
                  required
                />
              </div>
              <div>
                <label className="uppercase-label text-dim block mb-1">New Password</label>
                <input
                  type="password"
                  placeholder="New password"
                  value={newPass}
                  onChange={e => setNewPass(e.target.value)}
                  className="t-input w-full"
                  required
                />
              </div>
              <button type="submit" className="btn-primary">[ UPDATE PASSWORD ]</button>
              {passMsg && (
                passMsg.toLowerCase().includes('err') || passMsg.toLowerCase().includes('fail') || passMsg.toLowerCase().includes('invalid') || passMsg.toLowerCase().includes('incorrect') || passMsg.toLowerCase().includes('wrong')
                  ? <p className="text-xs font-mono" style={{ color: 'var(--color-danger, #ff4141)' }}>[ ERR: {passMsg} ]</p>
                  : <p className="text-green text-xs font-mono">[ OK: {passMsg} ]</p>
              )}
            </form>
          </div>

        </div>
      </main>
    </div>
  )
}
