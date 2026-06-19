import { expect, test } from '@playwright/test'

const apiBaseURL = process.env.NEXT_PUBLIC_API_URL ?? `http://localhost:${process.env.AUTH_SMOKE_API_PORT ?? 8001}`

async function loginAndToken(page: import('@playwright/test').Page) {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('USERNAME').fill('admin')
  await page.getByLabel('PASSWORD').fill('secret')
  await page.getByRole('button', { name: /^authenticate$/i }).click()
  await expect(page).toHaveURL(/\/$/)
  const accessToken = await page.evaluate(() => localStorage.getItem('access_token'))
  expect(accessToken).toBeTruthy()
  return accessToken as string
}

test('authenticated intelligence and watchlist APIs round-trip from the browser session', async ({ page }) => {
  const accessToken = await loginAndToken(page)
  const headers = { Authorization: `Bearer ${accessToken}` }

  const note = await page.request.post(`${apiBaseURL}/v1/intelligence/notes`, {
    headers,
    data: { entity_type: 'portfolio', entity_id: 'default', content: 'E2E portfolio review note' },
  })
  expect(note.ok()).toBe(true)
  const notePayload = await note.json()
  expect(notePayload.content).toBe('E2E portfolio review note')

  const notes = await page.request.get(`${apiBaseURL}/v1/intelligence/notes?entity_type=portfolio&entity_id=default`, { headers })
  expect(notes.ok()).toBe(true)
  const noteList = await notes.json()
  expect(noteList.some((row: { id: number }) => row.id === notePayload.id)).toBe(true)

  const watchlist = await page.request.post(`${apiBaseURL}/v1/watchlist`, {
    headers,
    data: {
      symbol: `E2E${Date.now().toString().slice(-6)}`,
      name: 'E2E Watch Candidate',
      market: 'TEST',
      asset_type: 'equity',
      priority: 'high',
      status: 'researching',
      target_entry_max: 42,
      thesis: 'Browser-authenticated watchlist smoke',
    },
  })
  expect(watchlist.ok()).toBe(true)
  const watchlistPayload = await watchlist.json()
  expect(watchlistPayload.priority).toBe('high')

  const rows = await page.request.get(`${apiBaseURL}/v1/watchlist`, { headers })
  expect(rows.ok()).toBe(true)
  const watchlistRows = await rows.json()
  expect(watchlistRows.some((row: { id: number }) => row.id === watchlistPayload.id)).toBe(true)
})
