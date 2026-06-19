import { expect, test } from '@playwright/test'

const apiBaseURL = process.env.NEXT_PUBLIC_API_URL ?? `http://localhost:${process.env.AUTH_SMOKE_API_PORT ?? 8001}`

test('authenticated app exposes owned-polling freshness status', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('USERNAME').fill('admin')
  await page.getByLabel('PASSWORD').fill('secret')
  await page.getByRole('button', { name: /^authenticate$/i }).click()

  await expect(page).toHaveURL(/\/$/)

  const accessToken = await page.evaluate(() => localStorage.getItem('access_token'))
  expect(accessToken).toBeTruthy()

  const response = await page.request.get(`${apiBaseURL}/v1/sync/freshness`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  })
  expect(response.ok()).toBe(true)

  const payload = await response.json()
  expect(payload.owned_polling).toMatchObject({
    enabled: true,
    cadence_seconds: 900,
  })
  expect(typeof payload.owned_polling.stale).toBe('boolean')
  expect(payload.binance_auto_sync).toMatchObject({
    enabled: false,
    cadence_seconds: 3600,
  })
  expect(typeof payload.binance_auto_sync.stale).toBe('boolean')
})
