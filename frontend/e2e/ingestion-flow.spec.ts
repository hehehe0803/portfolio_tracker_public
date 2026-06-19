import { expect, test } from '@playwright/test'
import {
  hasXtbWorkbookFixture,
  installXtbImportMocks,
  xtbWorkbookFixturePath,
} from './fixtures/xtb-ingestion-fixture'

test('uploads an XTB statement, reviews the preview, confirms the import, and refreshes history', async ({ page }) => {
  test.skip(!hasXtbWorkbookFixture, 'private XTB workbook fixture is local-only under data/')

  await installXtbImportMocks(page)

  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('USERNAME').fill('admin')
  await page.getByLabel('PASSWORD').fill('secret')
  await page.getByRole('button', { name: /^authenticate$/i }).click()

  await expect(page).toHaveURL(/\/$/)

  await page.goto('/import')
  await expect(page.getByText(/data ingest \/ broker imports/i)).toBeVisible()
  await expect(page.getByText(/no imports on record/i)).toBeVisible()

  await page.locator('#file-upload').setInputFiles(xtbWorkbookFixturePath)

  await expect(page.getByText(/\[ parse result: xtb_private_regression_workbook\.xlsx \]/i)).toBeVisible()
  await expect(page.getByRole('button', { name: /\[ commit 2 records \]/i })).toBeVisible()

  await page.getByRole('button', { name: /\[ commit 2 records \]/i }).click()

  await expect(page.getByText(/committed 2 transactions/i)).toBeVisible()
  await expect(page.getByText(/\[ parse result:/i)).toHaveCount(0)
  await expect(page.getByText(/\[ import history \]/i)).toBeVisible()
  await expect(page.getByText(/xtb_private_regression_workbook\.xlsx/i)).toBeVisible()
  await expect(page.getByText('COMMITTED', { exact: true })).toBeVisible()
})
