import { expect, type Page, test } from '@playwright/test'

async function openLogoutControl(page: Page) {
  const desktopLogout = page.getByRole('button', { name: /^logout$/i })
  if (await desktopLogout.isVisible()) return desktopLogout

  await page.getByRole('button', { name: /open navigation menu/i }).click()
  const menuLogout = page.getByRole('button', { name: /^logout$/i })
  await expect(menuLogout).toBeVisible()
  return menuLogout
}

test('redirects unauthenticated users, logs in, restores session, and logs out', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: /mission control/i })).toBeVisible()

  await page.getByLabel('USERNAME').fill('admin')
  await page.getByLabel('PASSWORD').fill('secret')
  await page.getByRole('button', { name: /^authenticate$/i }).click()

  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText(/total portfolio value/i)).toBeVisible()
  await openLogoutControl(page)

  await page.reload()
  await expect(page).toHaveURL(/\/$/)
  const logout = await openLogoutControl(page)

  await logout.click()
  await expect(page).toHaveURL(/\/login$/)

  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})
