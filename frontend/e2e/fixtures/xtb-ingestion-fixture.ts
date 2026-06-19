import { existsSync, readdirSync } from 'node:fs'
import path from 'node:path'
import type { Page } from '@playwright/test'

const fixtureDirectory = path.resolve(
  __dirname,
  '..',
  '..',
  '..',
  'data',
  'xtb_statement_reference'
)
const sanitizedFixtureName = 'xtb_private_regression_workbook.xlsx'
const workbookPattern = /^.+_en_xlsx_2025-09-07_2025-10-08\.xlsx$/
const matchingWorkbookNames = existsSync(fixtureDirectory)
  ? readdirSync(fixtureDirectory).filter((entry) => workbookPattern.test(entry))
  : []
const discoveredWorkbookName = matchingWorkbookNames.length === 1
  ? matchingWorkbookNames[0]
  : undefined

export const xtbWorkbookFixturePath = path.join(
  fixtureDirectory,
  discoveredWorkbookName ?? sanitizedFixtureName
)
export const hasXtbWorkbookFixture = existsSync(xtbWorkbookFixturePath)

const createdAt = '2026-04-14T05:00:00.000Z'
const committedAt = '2026-04-14T05:01:00.000Z'

const preview = {
  total_parsed: 2,
  new: 2,
  duplicates: 0,
  sample: [
    {
      date: '2026-04-13T00:00:00.000Z',
      type: 'BUY',
      symbol: 'AAPL',
      amount: 125.5,
      description: 'Buy Apple shares',
    },
    {
      date: '2026-04-13T00:00:00.000Z',
      type: 'DIVIDEND',
      symbol: 'AAPL',
      amount: 1.25,
      description: 'Cash dividend',
    },
  ],
}

const reviewedImport = {
  id: 1,
  institution: 'xtb',
  filename: sanitizedFixtureName,
  status: 'reviewed',
  parsed_count: 2,
  committed_count: 0,
  duplicate_count: 0,
  preview,
  error: null,
  created_at: createdAt,
  committed_at: null,
}

const committedImport = {
  ...reviewedImport,
  status: 'committed',
  committed_count: 2,
  committed_at: committedAt,
}

export async function installXtbImportMocks(page: Page) {
  let state: 'empty' | 'reviewed' | 'committed' = 'empty'

  await page.route('**/v1/imports/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const { pathname } = url
    const method = request.method()

    if (method === 'OPTIONS') {
      await route.continue()
      return
    }

    if (pathname === '/v1/imports/' && method === 'GET') {
      const body = state === 'empty' ? [] : [state === 'reviewed' ? reviewedImport : committedImport]
      await route.fulfill({ json: body })
      return
    }

    if (pathname === '/v1/imports/xtb' && method === 'POST') {
      state = 'reviewed'
      await route.fulfill({
        json: {
          artifact_id: reviewedImport.id,
          status: reviewedImport.status,
          preview: reviewedImport.preview,
          error: null,
        },
      })
      return
    }

    if (pathname === '/v1/imports/1' && method === 'GET') {
      await route.fulfill({ json: reviewedImport })
      return
    }

    if (pathname === '/v1/imports/1/confirm' && method === 'POST') {
      state = 'committed'
      await route.fulfill({
        json: {
          committed: committedImport.committed_count,
          duplicates_skipped: 0,
        },
      })
      return
    }

    await route.fallback()
  })
}
